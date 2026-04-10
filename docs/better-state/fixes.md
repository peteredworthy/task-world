# State Management Fixes

Each fix is labelled with the issues it resolves. See [issues.md](issues.md) for full issue descriptions and verification notes.

Fixes marked ~~struck through~~ were found to be unnecessary after code review.

---

## Confirmed fixes required

### FIX-4 — Wrap signal handlers in atomic transactions

**Resolves:** ISSUE-8.2

Signal handler contract: `BEGIN → mutate state → set handled_at → COMMIT`; rollback on any exception. `handled_at` is set if and only if all mutations committed. Redelivery after a crash re-applies the handler against unmodified state. SQLite serialises writes so the lock hold time is negligible — all operations are pure DB work with no external I/O.

This is the highest-priority confirmed fix: the mutation+redelivery combination can cause real duplicate state transitions.

---

### FIX-6 — Pre-persist safety pause before executor loop starts

**Resolves:** ISSUE-2.1

Before entering the executor loop, write `PAUSED/reason=executor_not_started` to the DB and commit. The loop's first action is to clear the safety pause atomically with its first heartbeat write. If the process is killed before the loop starts, the run is already `PAUSED` on next startup.

```python
await service.write_safety_pause(run_id, reason="executor_not_started")
await session.commit()
# loop starts — first thing inside clears the safety pause
await service.clear_safety_pause(run_id)
```

The existing `finally` block remains as a belt-and-suspenders fallback.

---

### FIX-7 — Optimistic version lock via SQLAlchemy version_id_col

**Resolves:** ISSUE-1.3, ISSUE-9.1

Use SQLAlchemy's built-in `version_id_col` — no hand-rolled version check needed. Add a `version` column to `TaskModel` and declare `__mapper_args__ = {"version_id_col": version}`. SQLAlchemy automatically increments on every UPDATE and raises `StaleDataError` on concurrent modification. Works identically on SQLite and PostgreSQL regardless of isolation level — detection is at the ORM layer.

Catch `StaleDataError`: for fan-out expansion (ISSUE-1.3), discard the duplicate expansion; for clarification/completion (ISSUE-9.1), surface a `409 Conflict`.

---

### FIX-12 — Record paused_at on in-progress Attempts

**Resolves:** ISSUE-4.1

Add `paused_at` (nullable timestamp) and allow `outcome = "paused"` on the `Attempt` model. When pause fires mid-BUILDING or mid-VERIFYING, set these fields before transitioning the run to `PAUSED`. On resume:
- `continue`: re-attach the agent to the paused attempt (file state is preserved in the worktree on a single machine)
- `revert`: explicitly mark the attempt `outcome = "abandoned"` before creating a fresh one

This makes the distinction between "paused", "abandoned", and "failed" explicit in the data model and prevents silent discards.

---

## Useful hygiene (low priority)

### FIX-16 — Structured GateBlockedEvent with unmet conditions

**Resolves:** ISSUE-7.2

When `_find_next_task()` returns `BLOCKED_BY_GATE`, capture `{gate_name, step_id, step_name, unmet_conditions[]}` and store it in a `gate_blocked_details` JSON column on the run. Emit a `GateBlockedEvent` carrying this payload. Expose via the run API response. The `ApprovalRequested` event already carries `step_id`, so this is an incremental improvement rather than a critical gap.

---

### FIX-17 — Audit log for run state mutations

**Resolves:** ISSUE-10.2

Add an `audit_log` table: `(id, run_id, actor, action, details JSON, request_id, ip_address, created_at)`. Write a record in state-mutating API handlers. Use request middleware to inject `request_id` and `ip_address`. The event log already covers workflow transitions; this fills the gap for direct mutations (e.g. `agent_config` updates) and adds actor context.

---

## Not required — already handled in code

### ~~FIX-1 — DB-backed locks~~
Neither ISSUE-3.1 nor ISSUE-3.2 require this. All in-process agent types die on restart; `engine.complete_verification()` already releases locks correctly. Relevant only if `OPENHANDS_DOCKER` with container-surviving-restart scenarios are adopted.

### ~~FIX-2 — SPAWNING intermediate run state~~
ISSUE-1.2 downgraded to LOW: the window between ACTIVE commit and executor task creation is sub-millisecond; the sweeper threshold is 120 seconds. ISSUE-2.3 is mitigated by the single-threaded lifespan. The added complexity of a new run state is not justified.

### ~~FIX-3 — Idempotent signal enqueue~~
ISSUE-1.1 and ISSUE-8.1 are guarded by run-status checks in the signal handlers. Duplicate signals produce wasted rows but no duplicate transitions. Good hygiene if the signal table needs a cleanup, but not a correctness fix.

### ~~FIX-5 — Global auto-increment sequence on events~~
ISSUE-5.1 is not real. `EventModel` already uses `AUTOINCREMENT` as its PK and events are queried `ORDER BY id`. SQLite write serialisation makes this deterministic. A separate `seq` column would duplicate the PK.

### ~~FIX-8 — Heartbeat on a separate asyncio.Task~~
ISSUE-2.2 is not real. The sweeper checks `_running_tasks` first; the heartbeat is only the fallback for PID-less phases. Long `agent.execute()` calls do not cause spurious pauses.

### ~~FIX-9 — Raise on journal failure; reconciliation tool~~
ISSUE-5.2 is design intent. The DB is the source of truth; the journal is optional durability hardening. The exception swallow is documented and intentional.

### ~~FIX-10 — Per-run asyncio.Lock around startup spawn~~
ISSUE-2.3 is mitigated by the single-threaded lifespan. Startup recovery cannot run concurrently with itself.

### ~~FIX-11 — DB retry via tenacity + pool_pre_ping~~
ISSUE-10.1 is accepted design for local SQLite with NullPool. No transient network errors apply. Relevant if PostgreSQL is adopted.

### ~~FIX-13 — Idempotent worktree creation~~
ISSUE-6.1 is already handled. `ensure_exists()` already exists and the normal code path already calls it.

### ~~FIX-14 — Gate worktree deletion on all fan-out children terminal~~
ISSUE-6.2 is mitigated by run structure. Fan-out children are TaskState objects within the same run sharing a single worktree; `handle_run_completion()` only fires when the run reaches terminal state, and the run cannot terminate while any child task is still executing.

### ~~Quick Win A — Explicit lock release~~
ISSUE-3.2 is already handled by `engine.complete_verification()`.

### ~~Quick Win B — Re-raise on pause failure~~
ISSUE-7.1 not found as described. `_emergency_pause()` intentionally catches in a callback context; the exception is logged at `exception` level.

---

## Deliberate non-fixes

| Issue | Decision |
|-------|----------|
| ISSUE-4.2 | Won't fix. Dirty worktree state is preserved by filesystem on single machine. Commit would require `--no-verify`, bypassing gitleaks. |
| ISSUE-9.2 | Accepted risk. Fan-out children sharing a worktree is intentional design. |
