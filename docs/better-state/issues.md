# State Management Issues

Issues identified through a deep-dive analysis of run state management and agent runner logic, verified against the actual source code.

---

## Severity Levels

- **CRITICAL** — Risk of silent data loss or undetectable corruption
- **HIGH** — Race condition that can corrupt state or cause duplicate execution
- **MEDIUM** — Degraded behaviour, resource leaks, or recoverable failures
- **LOW** — UX/observability gaps with no direct correctness risk

Statuses: **Confirmed** (real, unaddressed) · **Already handled** · **Design intent** · **Won't fix** · **Accepted risk** · **Overstated** (not a real problem)

---

## Category 1: State Machine Transitions

### ISSUE-1.1 — Duplicate RUN_START signals on concurrent `start_run()` calls
**Severity:** LOW (downgraded from HIGH after code review)
**Files:** `src/orchestrator/workflow/service.py`
**Status:** Guarded — no duplicate work possible

Two concurrent calls to `start_run()` can each enqueue a `RUN_START` signal row, since there is no uniqueness constraint on `pending_signals`. However, when the second signal is consumed, `apply_start_run()` checks that the run is still in `DRAFT` status before applying the transition. Once the first signal has been processed, the run is `ACTIVE` and the second signal fails this check and is discarded without side effects.

**Real risk:** Two signals in the table is wasteful but harmless — no duplicate agent spawns, no state corruption.

---

### ISSUE-1.2 — Resume sets ACTIVE in DB before agent is spawned
**Severity:** LOW (downgraded from HIGH after code review)
**Files:** `src/orchestrator/workflow/service.py`, `src/orchestrator/workflow/signals/consumer.py`
**Status:** Negligible in practice

After processing a RESUME signal, the run transitions to `ACTIVE` and the signal consumer immediately creates the executor asyncio task (`asyncio.create_task(...)`) in the same synchronous call before yielding. The window between ACTIVE being committed and the executor loop starting is sub-millisecond in normal operation. The stale-run sweeper threshold is 120 seconds. The probability of the sweeper firing in this window approaches zero.

**Real risk:** Theoretical. Not a practical concern at current sweep interval.

---

### ISSUE-1.3 — TOCTOU race in fan-out expansion
**Severity:** HIGH
**Files:** `src/orchestrator/workflow/service.py`
**Status:** Confirmed

Two concurrent callers can both read a `PENDING` parent task before either writes `FAN_OUT_RUNNING`. Each expands independently, producing duplicate child tasks. No row-level lock guards the read-expand-write sequence.

**Worst case:** Duplicate child tasks; same work executed twice; wasted tokens and potentially conflicting worktree commits.

---

## Category 2: Executor Lifecycle

### ISSUE-2.1 — Executor can exit without persisting a pause
**Severity:** MEDIUM (downgraded from CRITICAL after code review)
**Files:** `src/orchestrator/workflow/signals/runtime.py`
**Status:** Confirmed — sweeper provides eventual mitigation but with delay

The executor's `finally` block calls `apply_pause_run()`. If the DB is unavailable at shutdown this call is caught and only logged, leaving the run `ACTIVE`. The stale-run sweeper will eventually detect the orphaned ACTIVE run and pause it, but this is async and may take up to the sweep interval.

**Worst case:** Run stays `ACTIVE` until sweeper fires; on the next startup a new executor may be spawned against partially-executed state.

---

### ISSUE-2.2 — Heartbeat goes stale during long `agent.execute()` calls
**Severity:** NONE
**Files:** `src/orchestrator/runners/executor.py`
**Status:** Already handled — design is intentional

The sweeper's primary liveness check is `_running_tasks`, not the heartbeat. If a run is in `_running_tasks`, `is_running()` returns `True` immediately without consulting the heartbeat at all. The heartbeat is only used as a fallback for PID-less phases (verification, fan-out coordination, cleanup) where no subprocess entry exists. The 120-second threshold is irrelevant during active `agent.execute()` calls.

---

### ISSUE-2.3 — Agent spawn race during startup recovery
**Severity:** LOW (downgraded from HIGH after code review)
**Files:** `src/orchestrator/api/app.py`
**Status:** Mitigated by single-threaded lifespan

The startup recovery loop runs in the FastAPI lifespan context as a single asyncio coroutine. It cannot run concurrently with itself. A concurrent API request could theoretically call into the executor during recovery, but `spawn_for_run()` writes to `_running_tasks[run_id]` which is a dict — a second caller for the same run_id would overwrite the task reference, leaking the first task. This is an edge case that requires a request to arrive for a specific run_id within the few milliseconds of startup processing.

**Real risk:** Low. The lifespan serialises recovery; the edge case requires precise timing.

---

## Category 3: Lock Management

### ISSUE-3.1 — In-memory locks provide no cross-restart protection for long-lived agent types
**Severity:** LOW
**Files:** `src/orchestrator/workflow/locks.py`
**Status:** Not a concern for current deployment

All agent types in this deployment (`CLI_SUBPROCESS`, `OPENHANDS_LOCAL`, `CLAUDE_SDK`, `CODEX_SERVER`) die on server restart and are explicitly handled in startup recovery. The entire system uses `agent_id="default"` consistently — no mismatch. DB-backed locks would only matter for `OPENHANDS_DOCKER` agents where containers survive restarts, which is not the current deployment model.

---

### ISSUE-3.2 — Lock release on task completion
**Severity:** NONE
**Files:** `src/orchestrator/workflow/engine/engine.py`
**Status:** Already handled

`engine.complete_verification()` at line 515 releases the lock on `COMPLETED` or `FAILED`. The lock is intentionally held through revision cycles (`BUILDING → VERIFYING → BUILDING`). This is correct behaviour.

---

## Category 4: Pause / Resume

### ISSUE-4.1 — No checkpoint on pause; task progress is lost
**Severity:** MEDIUM
**Files:** `src/orchestrator/state/models.py`, `src/orchestrator/workflow/service.py`
**Status:** Confirmed

The `Attempt` model has no `paused_at` field and no `outcome="paused"` value. When a run is paused mid-BUILDING, the open attempt has no timestamp and no outcome. There is no way to distinguish an attempt that was paused-and-should-continue from one that was abandoned. The run itself records `pause_reason`, but this is at the run level, not the attempt level.

**Worst case:** Revert-resume silently discards an attempt that still has live worktree state; work is repeated.

---

### ISSUE-4.2 — Worktree may be dirty when pause fires
**Severity:** MEDIUM
**Files:** `src/orchestrator/workflow/service.py`
**Status:** Won't fix

On a single machine, dirty worktree state survives server restarts via the filesystem. For `continue` resume the files are already present. For `revert` resume the state is intentionally discarded. A commit would require `--no-verify`, bypassing gitleaks on partial agent output. Fixing ISSUE-6.1 and ISSUE-6.2 is sufficient. Revisit if multi-machine deployments become a requirement, using a patch-file artifact rather than a git commit.

---

## Category 5: Event / Journal Consistency

### ISSUE-5.1 — Event ordering is non-deterministic under concurrent writes
**Severity:** NONE
**Files:** `src/orchestrator/db/orm/models.py`, `src/orchestrator/db/access/event_store.py`
**Status:** Already handled — AUTOINCREMENT PK guarantees ordering

`EventModel` uses `AUTOINCREMENT` as its primary key and events are queried `ORDER BY id`. Because SQLite serialises all writes at the transaction level, the autoincrement ID assignment order is identical to logical commit order. Concurrent writes cannot produce out-of-order IDs. The separate `seq` column proposed in FIX-5 would duplicate what the PK already provides.

---

### ISSUE-5.2 — Event journal append failures are silently swallowed
**Severity:** LOW (downgraded from CRITICAL after code review)
**Files:** `src/orchestrator/db/access/event_store.py`
**Status:** Design intent — DB is source of truth

The exception swallow in `_append_journal_entries()` is documented as intentional. The DB event row is flushed before the journal write, so the event is durably persisted. The journal is explicitly described as "optional durability hardening" for forensic analysis; it is not the source of truth for online operation. A filesystem failure causing journal divergence does not affect correctness — only the ability to replay from the JSONL file.

---

## Category 6: Worktree Lifecycle

### ISSUE-6.1 — Worktree creation is not idempotent; orphans can accumulate
**Severity:** LOW (downgraded from MEDIUM after code review)
**Files:** `src/orchestrator/git/worktree.py`
**Status:** Already handled — callers use `ensure_exists()`

`WorktreeManager.ensure_exists()` already exists and is idempotent: it checks for an existing worktree by branch name before creating. In `app.py`, the normal code path already calls `ensure_exists()`, not `create()`. The public `create()` method raises `WorktreeExistsError` on collision rather than silently orphaning. The risk is limited to callers incorrectly using `create()` directly.

---

### ISSUE-6.2 — Worktree deletion can race with a still-running fan-out child
**Severity:** LOW (downgraded from MEDIUM after code review)
**Files:** `src/orchestrator/api/app.py`, `src/orchestrator/workflow/completion.py`
**Status:** Mitigated by run structure

Fan-out child tasks are `TaskState` objects within the same run — they all share the parent run's single worktree (`run.worktree_path`). However, worktree cleanup fires via `handle_run_completion()` only when the run itself reaches a terminal state, and the run cannot reach terminal state while any of its tasks (including fan-out children) are still executing. Therefore the cleanup-vs-still-executing-child race cannot occur through normal completion paths. Note: ISSUE-9.2 covers the separate and accepted risk of concurrent children writing conflicting changes within the shared worktree.

---

## Category 7: Error Propagation

### ISSUE-7.1 — Agent errors may not surface to run state when the pause call fails
**Severity:** NONE
**Files:** `src/orchestrator/runners/executor.py`
**Status:** Not found as described

Code review found `_emergency_pause()` which wraps `apply_pause_run()` in a try/except and logs the exception. This is intentional defensive programming in an asyncio callback context — the catch prevents failure of the cleanup path from propagating upward unhandled. The exception is logged as `exception` level (not silently swallowed). The run will be detected by the stale-run sweeper if the pause fails.

---

### ISSUE-7.2 — Gate blockage reason is an unstructured string
**Severity:** LOW
**Files:** `src/orchestrator/workflow/signals/runtime.py`
**Status:** Partially addressed

The `pause_reason` string `"awaiting_approval"` is deliberately simple. The `ApprovalRequested` event (emitted alongside the pause) carries `step_id`, providing enough context to identify the blocking step. The specific gate conditions that are unmet are not captured in any structured field, so diagnosing complex gate requirements still requires manual inspection. This is a UX gap, not a correctness issue.

---

## Category 8: Signal Queue

### ISSUE-8.1 — Concurrent pause/cancel requests produce duplicate signals
**Severity:** LOW (downgraded from MEDIUM after code review)
**Files:** `src/orchestrator/workflow/service.py`
**Status:** Guarded — duplicate transitions not possible

`pause_run()` checks that the run is `ACTIVE` before enqueuing; `cancel_run()` checks that the run is not already terminal. Two concurrent pause signals can be enqueued, but when the second is consumed the run is already `PAUSED` and the handler rejects the transition. No oscillation is possible from duplicate signals of the same type.

The PAUSE+RESUME rapid-fire oscillation scenario is real but requires deliberate rapid-fire API calls, not accidental concurrency.

---

### ISSUE-8.2 — Signal handler crash leaves partial mutations committed and signal unhandled
**Severity:** HIGH
**Files:** `src/orchestrator/workflow/signals/consumer.py`
**Status:** Confirmed

Verified in code: if a signal handler raises an exception mid-execution, `delivered_at` was already flushed and any mutations already applied are committed at line 244 (`await session.commit()`). The `handled_at` stays `NULL`, making the signal eligible for redelivery. On redelivery the handler runs again against already-mutated state. For idempotent handlers this is harmless; for non-idempotent ones (e.g., a handler that creates rows) it can produce duplicates.

**Worst case:** Redelivery of a partially-applied signal causes duplicate state mutations or an invalid transition that loops.

---

## Category 9: Concurrent Request Hazards

### ISSUE-9.1 — Clarification response and agent task-completion race on the same task
**Severity:** LOW (downgraded from HIGH after code review)
**Files:** `src/orchestrator/workflow/service.py`, `src/orchestrator/runners/executor.py`
**Status:** Largely serialised in practice

The executor loop is a single asyncio task per run that processes one operation at a time. Signal consumers are also serialised per `run_id`. The race window requires a direct API call to `clarification_response` to arrive and commit between two `await` points inside the executor's task processing — possible but narrow. No optimistic lock exists, so a true concurrent write would silently discard one update.

**Real risk:** Narrow but not zero. A production system under load could hit this.

---

### ISSUE-9.2 — Concurrent fan-out children share a worktree
**Severity:** MEDIUM
**Files:** `src/orchestrator/runners/executor.py`
**Status:** Accepted risk — intentional design

Fan-out children share a worktree by design. Children are expected to coordinate by operating on distinct parts of the codebase. See rationale above.

---

## Category 10: Operational Safeguards

### ISSUE-10.1 — No retry or circuit breaker on transient DB errors
**Severity:** LOW (downgraded from HIGH after code review)
**Files:** `src/orchestrator/db/access/connection.py`
**Status:** Accepted design — NullPool + local SQLite

The engine uses `NullPool` (fresh connection per session, no pooling). For a local SQLite database, transient network errors don't apply; the only failure modes are filesystem errors or SQLite busy/locked conditions, which are extremely rare in a single-writer setup. This is an appropriate trade-off for the stated architecture. `pool_pre_ping` and retry logic are relevant if PostgreSQL or a remote DB is ever adopted.

---

### ISSUE-10.2 — No audit trail for run state mutations
**Severity:** LOW (downgraded from MEDIUM after code review)
**Files:** `src/orchestrator/db/access/repositories.py`
**Status:** Partially addressed by event log

Major workflow state transitions (run status changes, task status changes, agent death, step completion) are captured as typed events in the event log with timestamps. Direct `repo.save()` mutations (e.g., updating `agent_config`) are not event-sourced. For operational purposes the event log provides a reasonable audit trail; for compliance/forensic purposes the direct mutations are a gap.

---
