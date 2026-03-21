# Executor Death Loop Investigation (Mar 17, 2026)

## Symptom

Run `739f0367-53d1-4ba9-b044-9a33c64294e1` (and others) would be paused with
`no_executor_running` within 60 seconds of every manual resume, creating an
infinite pause/resume death loop.

---

## Root Causes Found

### 1. Duplicate server processes (primary cause of the death loop)

Two separate uvicorn processes were running simultaneously, both reading from and
writing to the same `orchestrator.db`:

| Process | Started | Listening |
|---------|---------|-----------|
| 41992/41994 | Monday 5PM | `localhost:8000` |
| 10647/10649 | Today 12:46PM | `*:8000` |

Each server has its own in-memory `AgentRunnerExecutor` with an independent
`_running_tasks` dict and sweeper coroutine.

**Death loop mechanism:**
1. User resumes run → resume request hits **Server A** → adds executor task to
   Server A's `_running_tasks`
2. Server B's sweeper fires → checks **Server B's** `_running_tasks` (empty for
   this run) → `is_running()` returns False
3. Server B calls `service.pause_run(reason="no_executor_running")` via the
   shared DB
4. Executor on Server A continues running; its subprocess eventually calls
   `on_submit()` → fails with `InvalidTransitionError: paused →
   submit_for_verification` → logged as `AgentExecutionError`

This produced a repeating 60-second pause cycle with no useful diagnostic
information in the UI (pause reason showed `no_executor_running` only).

**Fix:** Kill the stale Monday server (`kill 41992 41994`). Only one server
should be bound to port 8000 at a time.

---

### 2. `AgentCancelledError` left run ACTIVE

When the executor received `AgentCancelledError` (e.g. the subprocess was
cancelled mid-task), the handler did:

```python
except AgentCancelledError:
    logger.info(f"Run {run_id}: agent cancelled")
    break  # ← no pause_run() call
```

The `break` exited the loop without pausing the run. On the next sweeper cycle,
the run was ACTIVE with no executor → paused with `no_executor_running`.

**Fix:** Call `service.pause_run(run_id, reason="agent_cancelled")` before
`break`.

---

### 3. No safety net in the executor `finally` block

If any code path exited the `while True` loop via `break` without calling
`pause_run()`, the run stayed ACTIVE. The sweeper was the only thing that would
eventually catch it (after up to 60 seconds).

**Fix:** Added a safety-net check in the `finally` block of `_run_agent_loop`:

```python
# In finally block, BEFORE _running_tasks.pop():
run = await repo.get(run_id)
if run.status == RunStatus.ACTIVE:
    logger.warning(f"Run {run_id}: executor exiting with run still ACTIVE — pausing (safety net)")
    await service.pause_run(run_id, reason="executor_exited")
    await session.commit()
```

---

### 4. `pause_reason` missing from journal events

`RunStatusChanged` events in the JSONL journal did not include the `pause_reason`
field. This made diagnosing pause events from the journal impossible — all pauses
looked identical.

**Fix:** Added `pause_reason: str | None = None` to the `RunStatusChanged`
dataclass and included it in `engine.pause_run()`'s event emission.

---

## Timeline of the 739f0367 death loop

| UTC Time | Event |
|----------|-------|
| 17:06–17:32 | Regular 60-second sweeper pauses (old code, no cause visible) |
| 17:27–18:08 | Zombie subprocess from previous session submits output |
| 18:08 | `agent_error`: zombie's submit fails |
| 19:49:42 | User resumes → ACTIVE (new server after hot-reload) |
| 19:49:49 | Server B's sweeper fires 7s later → `no_executor_running` |
| 21:31:34 | User resumes again → spawned on Server C |
| 21:32:30 | Server B's sweeper fires (its `_running_tasks` empty) → pause |
| 21:34:41 | Zombie subprocess completes, `on_submit` fails with `InvalidTransitionError` |

---

## Fixes Committed

**Commit `a4b28d1`** — `Fix executor death loop: pause on AgentCancelledError, add safety-net pause, include pause_reason in events`

Files changed:
- `src/orchestrator/runners/executor.py` — AgentCancelledError handler + finally safety net
- `src/orchestrator/workflow/engine.py` — include pause_reason in RunStatusChanged event
- `src/orchestrator/workflow/events.py` — add pause_reason field to RunStatusChanged

**Commit `672efc7`** — `Extract resolve_no_task_action() pure function; add state machine test suite`

This earlier commit added heartbeat tracking to `is_running()` and enforced the
invariant that every `NoTaskReason` path pauses the run. 31 unit tests +
7 integration tests guard the executor state machine.

---

## Lingering Risk

If a hot-reload happens while an agent is actively running a subprocess:
1. The old executor receives `asyncio.CancelledError`
2. The `except asyncio.CancelledError` handler calls `pause_run("server_shutdown")`
3. If the DB/session is already closing, this fails silently
4. The new server's `recover_active_runs_on_startup()` pauses ACTIVE runs with
   `agent_not_running_on_startup` as a fallback
5. Auto-resume fires for `server_shutdown` and `agent_not_running_on_startup` runs

The subprocess (zombie) survives the reload and continues running. It cannot
submit because the run is PAUSED during the reload window. The auto-resume
spawns a NEW subprocess. Both may briefly overlap.

This is a known acceptable trade-off for the dev hot-reload scenario. In
production (no hot-reload), this path does not trigger.

---

## Prevention

- **Never run two server instances against the same DB.** Check with
  `ps aux | grep uvicorn` and `lsof -i :8000` before starting.
- The `dev.sh` script starts with `--reload-dir src --reload-dir scripts` to
  restrict file watching to source directories only (not worktrees).
- If the server was started from two different terminals, kill all but one.
