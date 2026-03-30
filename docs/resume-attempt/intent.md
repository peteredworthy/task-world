# Intent: Attempt UUID, Drop agent_output, Fan-out Dead Code Removal

## Background

Agent output is currently stored in two places:

1. **`attempts.agent_output` (TEXT column)** — written once when the agent finishes. Empty for any attempt interrupted by a server crash. No recovery path.
2. **`events` table (rows with `event_type='agent_output'`)** — written incrementally as the agent streams output. Survives server crashes. Already has `timestamp` and `line_offset` for ordering.

The `attempts.agent_output` column is therefore a lossy, redundant cache of data that already lives in `events`. The only functional consumer — template variable resolution via `steps.S1.output` — is dead code in any real routine. The viewer endpoint and `has_output` flag can both be served from `events` directly.

This work removes the column and makes `events` the single source of truth for agent output, while also fixing attempt UUID assignment so events can be correctly correlated to the attempt that produced them across server restarts.

---

## Part 1: Attempt UUID

### Current state

- `attempts.id` — UUID primary key, generated at row creation. This IS the stable attempt UUID.
- `attempts.attempt_id` — added later (migration `k1a2b3c4d5e6`), always set to the same value as `id`. **NULL for all existing rows** because the migration added it nullable and the backfill was never run. Intended for "Temporal Activity ID mapping" that isn't wired up.
- `AgentOutputEvent` carries `attempt_num` (integer) and `task_id`, but not the attempt UUID. If a run is paused, the agent dies, and a new attempt is created on resume, `attempt_num` increments — but within a single attempt, if the server crashes and the *same* agent subprocess resumes, the `attempt_num` stays the same while `line_offset` resets to 0. Without the UUID there is no way to detect the seam.
- `Attempt` (in-memory model) has `id: str = Field(default_factory=generate_id)` — this UUID is used as the ORM primary key but is never surfaced to the API or stored in events.

### What to do

**1a. Confirm `attempt_id` is redundant with `id`, drop it.**
`AttemptModel.attempt_id` is always set to `attempt.id`. It adds confusion without value. Drop the column and the migration that added it.

**1b. Populate `attempt_id` in `AgentOutputEvent`.**
Add `attempt_id: str = ""` to `AgentOutputEvent`. The `PhaseHandler` constructs these events; at that point `task_state.attempts[-1].id` is the current attempt UUID. Pass it through.

**1c. Add `attempt_id` to `AttemptSchema` (API response).**
Clients need the UUID to correlate log events to attempts. Add `attempt_id: str` to `AttemptSchema`, populated from `Attempt.id`.

**1d. Ensure `Attempt.id` is correctly round-tripped through the DB.**
Verify that when loading attempts from the DB, `AttemptModel.id` is mapped back to `Attempt.id`. If the current mapping generates a new UUID on load (rather than reading from the row), fix it. All code paths that construct `Attempt` from `AttemptModel` must copy `id` not generate a fresh one.

**1e. Write an Alembic migration** to populate `attempt_id = id` for all existing NULL rows, then drop `attempt_id`. (Effectively a no-op cleanup since `attempt_id = id` always — the real gain is step 1b above.)

---

## Part 2: Drop `agent_output`

### Current consumers (all to be replaced or removed)

| Location | Use | Replacement |
|---|---|---|
| `routers/tasks.py:219` | `has_output=bool(att.agent_output)` | Boolean flag on attempt row, set True on first output event (see below) |
| `routers/tasks.py:728` | Output viewer endpoint reads raw text | Reconstruct from events (see below) |
| `routers/tasks.py:732-739` | NDJSON backfill — re-parses raw output to recover `action_log` for old attempts | Drop entirely. `action_log_json` is populated correctly by current agents. |
| `transitions.py:995-1009` | `steps.S1.output` template variable | Dead code — remove (see Part 3) |
| `service.py:1445,1532` | Script task completion sets `attempt.agent_output = output` | Remove. Script task output should be emitted as events instead, or dropped if not needed. |
| `state/models.py:163` | `Attempt.agent_output` field | Remove field |
| `db/orm/models.py:200` | `AttemptModel.agent_output` column | Remove field + Alembic migration to drop column |
| `repositories.py:76-85` | Deferred load of `agent_output` | Remove deferral |
| `repositories.py:789-795` | `update_latest_attempt` appends `output_lines` | Remove `output_lines` parameter |
| `attempt_store.py` | `store_attempt_output` writes to column | Remove write to `agent_output`; keep the method if it still does other work (error, action_log) |

### `has_output` flag

Rather than querying the events table per-attempt at list time, add a `has_output: bool` column to `attempts` (default False). Set it to True the first time any `agent_output` event is persisted for that attempt. This keeps the list endpoint O(1) per attempt.

Update `store_attempt_output` (or wherever output lines are handled) to set `has_output = True` on the attempt row after the first event write. This is a one-time toggle — no need to track count.

### Output viewer endpoint

`GET /{run_id}/tasks/{task_id}/attempts/{attempt_num}/logs` currently reads `attempt.agent_output`. Replace with:

1. Look up the attempt row to get its UUID (`attempt.id`).
2. Query `events` for all rows where `run_id = X`, `event_type = 'agent_output'`, `payload->>'attempt_id' = UUID`, ordered by `timestamp ASC`.
3. Concatenate all `lines` arrays in order to reconstruct the full output text.

Note: `line_offset` cannot be used as the primary ordering key because it resets to 0 if a server restarts and the same attempt resumes. Use `timestamp` as the sort key. `line_offset` is only valid within a single continuous streaming session and should be treated as advisory.

For the action log: `action_log_json` remains on the attempt row, populated by the agent at completion. The NDJSON backfill (`_looks_like_ndjson_agent_stream` / `_parse_action_log_from_raw`) is removed since it only existed to recover `action_log` from `agent_output` for older attempts.

### Alembic migration

Drop `agent_output` TEXT column from `attempts`. Accept data loss for completed attempts that have `agent_output` populated — their output already exists in `events` (written incrementally during execution), so nothing new is lost.

---

## Part 3: Fan-out Dead Code Removal

### The two fan-out mechanisms

**File-glob fan-out** (`expand_fan_out_task`, `service.py`): Driven by `task_config.fan_out.input_glob`. Globs the worktree, creates one child `TaskState` per matched file. Completely independent of `agent_output`. **No changes needed here.**

**`repeat_for` step expansion** (`transitions.py`): Driven by `step_config.condition.repeat_for`. Resolves a variable at runtime and creates N step copies. Two variable sources exist:
- `context.*` — reads from run config dict. **Used in all real routines** (e.g., `repeat_for: "env in context.environments"`). Keep this.
- `steps.STEP_ID.output` / `steps.STEP_ID.task_outputs` — reads `agent_output` strings from completed tasks. **Used in no real routine.** The code returns the entire agent output string as an opaque list element — not parsed, not split. This cannot produce a meaningful list for iteration unless each prior task happens to produce a one-item result. Dead.

### What to remove

- `_get_variable_value_for_repeat`: remove the `steps.*` branch entirely (`transitions.py:958-1017`). Only `context.*` should remain. Update the error message to reflect the narrower supported syntax.
- `transitions.py` property resolution for `"output"` and `"task_outputs"` (lines 985-1011) — the entire `steps` block.
- Unit tests in `test_repeat_for_expansion.py` that test `steps.S1.output` and `steps.S1.task_outputs` resolution.
- Integration test in `test_conditional_steps.py` that uses `repeat_for="item in steps.S1.output"`.
- The `task_outputs` property path in `_get_variable_value_for_repeat`.

---

## Part 4: Other Cleanup Required

### `event_type='agent_output'` in recovery matrix

`recovery.py` lists `agent_output` events as `"informational"` — no state changes applied on replay. This is correct and should stay. The classification doesn't need changing; these events were always informational and now become the primary output store, but replay still doesn't need to reconstruct text output.

### Script task output (`service.py:1445,1532`)

Script tasks set `attempt.agent_output = output` directly at completion (not through the streaming path). After dropping the column, script task output either needs to be emitted as `agent_output` events or dropped. Check whether script task output is surfaced anywhere meaningful; if not, drop the assignment. If it is needed, emit a single `agent_output` event with the full output as `lines`.

### Frontend

`has_output` in `AttemptSchema` continues to exist as a boolean — source changes from `bool(att.agent_output)` to the new boolean column on the attempt row. No frontend changes required.

`attempt_id` added to `AttemptSchema` — frontend can use this to correlate live WebSocket `agent_output` events to the correct attempt. The WebSocket events already carry `attempt_num` and `task_id`; adding `attempt_id` makes the correlation UUID-based.

### Test suite

Anything that constructs `Attempt(agent_output=...)` directly or asserts on `attempt.agent_output` needs updating. Specifically:
- `repositories.py` tests that populate `agent_output` to test deferred loading
- Unit tests for `update_latest_attempt` with `output_lines`
- Any test that uses the output viewer endpoint and provides pre-populated `agent_output`

---

## What Is Not Changing

- `action_log_json` on the `attempts` table — structured tool call log, correctly populated by current agents, stays as-is.
- The WebSocket streaming path — `agent_output` events are broadcast live via WebSocket during execution. This continues unchanged; the event schema just gains `attempt_id`.
- `events` table schema — no structural changes; `AgentOutputEvent.attempt_id` is a new field in the JSON `payload` column, handled via the existing serialisation path.
- `fan_out` task execution itself — only the dead `repeat_for` variable source path is removed.
