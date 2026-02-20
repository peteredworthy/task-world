# Niggles Fix Plan

## Issue Registry

All 14 issues must be resolved. This ID list is the verification checklist.

| ID  | Source          | Summary                                                        |
|-----|-----------------|----------------------------------------------------------------|
| D1  | Dashboard-view  | Past revision attempts show "Needs revision" not "Building…"  |
| D2  | Dashboard-view  | Passed attempts show "Accepted" not "Passed"                  |
| Q1  | Questions       | Remove clarification auto-popup; clickable button only        |
| Q2  | Questions       | Restyle pending-action bar indicator                          |
| Q3  | Questions       | Answering clarification re-spawns agent (resume run if paused)|
| DV1 | Details-view    | Both builder AND verifier prompts always accessible           |
| DV2 | Details-view    | Collapsible step sections (not a flat task list)              |
| R1  | Repositories    | Add/remove repos (URL clone or filesystem path symlink)       |
| R2  | Repositories    | Expandable repo cards                                         |
| R3  | Repositories    | Expanded view shows most recent branches                      |
| R4  | Repositories    | Expanded view shows run count → links to filtered dashboard   |
| V1  | Validation      | Detect validation-script crash vs ordinary non-zero exit      |
| V2  | Validation      | Trigger recovery agent on crash or max-attempts exceeded      |
| V3  | Validation      | Recovery agent can ask user questions via clarification system |

---

## Group 1 — Dashboard Attempt Labels (D1, D2)

### D1 — "Needs revision" for revision-cycle attempts

**Root cause**: `attempts_summary` items have `outcome: null` while the attempt is
in-flight. When an attempt finishes as a revision cycle the `outcome` field is set
to `"revision_needed"` in the DB. In the UI, the label function maps `null` → "Building…".
For attempts that are *older* than `task.current_attempt`, null outcome must be
treated as a revision (the current code has no such fallback).

**File**: `ui/src/lib/outcome.ts`
- Change `outcomeLabel('revision_needed')` → `'Needs revision'`

**File**: `ui/src/components/dashboard/RunCard.tsx`
- In the `attempts_summary` map, when `att.outcome === null`:
  - If `att.attempt_num < task.current_attempt` → display `"Needs revision"` (past attempt, definitely finished)
  - Otherwise → keep `"Building…"` (current in-flight attempt)

### D2 — "Accepted" for passed attempts

**File**: `ui/src/lib/outcome.ts`
- Change `outcomeLabel('passed')` → `'Accepted'`

---

## Group 2 — Clarifications UI (Q1, Q2, Q3)

### Q1 — Remove auto-popup

**File**: `ui/src/pages/RunDetail.tsx`
- Remove the `useEffect` that auto-sets `selectedPendingAction` when
  `taskPendingActions` becomes non-empty.
- The pending-actions banner already has a "Review" button — that stays as the
  only trigger.
- Keep `selectedPendingActionRef` guard intact so a dismissed modal does not
  re-open automatically.

### Q2 — Restyle the pending-action bar

**File**: `ui/src/pages/RunDetail.tsx` (the yellow "Action required" banner,
lines ~410–432)

Replace the current banner with a compact, design-system-aligned component:
- Single line height, no word-wrap for the action count badge
- Use the app's existing colour tokens (`bg-bg-elevated`, `border-accent-purple/40`,
  `text-text-primary`, etc.) — NOT ad-hoc yellow
- Left side: icon + concise label ("N action(s) required")
- Right side: a small "Review →" button (ghost or outline, consistent with other
  secondary actions in the UI)
- Economical with vertical space; no multi-line text wrapping

### Q3 — Re-spawn agent (and resume run) after answering

**File**: `src/orchestrator/api/routers/clarifications.py`

After `service.respond_to_clarification(...)` succeeds, update the re-spawn
logic:
1. Re-fetch the run
2. If `run.status == RunStatus.PAUSED` → call `await service.resume_run(run_id)`
   before spawning (so the run shows ACTIVE in the UI again)
3. **Always** spawn the agent regardless of previous status check — remove the
   `if run.status == RunStatus.ACTIVE` guard (or expand it to also cover PAUSED
   after the resume)

---

## Group 3 — Details View (DV1, DV2)

### DV1 — Both prompts always accessible

**Problem**: During VERIFYING, `att.builder_prompt` is set (stored) but
`att.verifier_prompt` is still `null`. The live API (`useTaskPrompt`) returns
the current phase's prompt. The existing UI condition
`{!att.builder_prompt && apiPrompt && ...}` means the live API result is only
used as a builder-prompt fallback, never as a supplementary verifier prompt.

**Fix** — `ui/src/components/detail/TaskDetailCard.tsx` (inside `AttemptCard`):

```
Builder prompt:
  - If att.builder_prompt → show it
  - Else if apiPrompt?.phase === 'building' → show apiPrompt (system + user)
  - Else → show nothing (historical attempt with no stored prompt)

Verifier prompt:
  - If att.verifier_prompt → show it
  - Else if apiPrompt?.phase === 'verifying' → show apiPrompt (system + user)
  - Else → show nothing
```

This ensures:
- During BUILDING: builder prompt shows from live API (or stored), verifier absent ✓
- During VERIFYING: both builder (stored) and live verifier show ✓
- After COMPLETED: both stored prompts show ✓

### DV2 — Collapsible step sections

**File**: `ui/src/components/detail/ActivityFeed.tsx`

Replace the flat task-card list with step-scoped collapsible sections:

1. **Group** tasks by step using `run.steps` (already available from the `run` prop)
2. For each step, render a `StepSection` component:
   - **Header** (always visible): step number pill + step title + task-count
     progress badge (e.g. "2 / 3") + chevron toggle
   - **Body** (collapsible): the existing `TaskDetailCard` / `TaskGroupCard`
     components for that step's tasks
3. **Default expand state**:
   - Completed steps → collapsed by default
   - Current step (contains any non-COMPLETED non-FAILED task) → expanded
   - Steps with failed tasks → expanded
4. Users can manually toggle any step
5. Milestone events remain suppressed (no change)
6. Scroll anchors (`id="step-{step.id}"`) move to the section header so the
   progress-bar pills still scroll to the right place

---

## Group 4 — Repositories (R1, R2, R3, R4)

### R1 — Add / remove repositories

**Backend**

`src/orchestrator/api/routers/repos.py`:

Add `POST /api/repos` accepting JSON body `{ "url": "https://..." }` OR
`{ "path": "/absolute/or/relative/path" }`:
- **URL**: Run `git clone <url> <repos_dir>/<inferred-name>` via asyncio
  subprocess. `inferred-name` = last path segment of URL, strip `.git` suffix.
  Return the new `RepoResponse` on success.
- **Path** (filesystem): Verify path exists and is a git repo (`.git` dir).
  If the path is already *inside* `repos_dir`, return the existing entry.
  If outside, create a symlink: `repos_dir/<basename> → <absolute-path>`.
  Return the new `RepoResponse`.
- 409 if name already exists. 422 for invalid input.

Add `DELETE /api/repos/{name}`:
- Determine if the entry is a symlink or a real directory.
  - Symlink → `unlink` it.
  - Real directory → confirm it is inside `repos_dir`, then `shutil.rmtree`.
- Return 204 No Content.

`src/orchestrator/api/schemas/repos.py`:
- Add `AddRepoRequest(BaseModel)` with optional `url: str | None` and
  `path: str | None` (at least one required).

**Frontend**

`ui/src/pages/Repos.tsx`:
- Add an "Add Repository" button (top-right of the page header, consistent style
  with other primary actions).
- Clicking opens a small modal with two tabs: "By URL" / "By Path", plus an
  input field and a Submit button.
- After success, invalidate the repos query (`queryClient.invalidateQueries`).

`ui/src/pages/Repos.tsx` (RepoCard):
- Add a "Remove" icon-button (trash icon, ghost variant, right-side of card
  header).
- On click: show a confirmation popover ("Remove this repository?") before calling
  `DELETE /api/repos/{name}`.

### R2 — Expandable repo cards

**Frontend** `ui/src/pages/Repos.tsx`:
- Make `RepoCard` expandable: clicking the card body (not the buttons) toggles
  expanded state.
- Show a chevron indicator in the card header.
- Expanded area (lazy-loaded on first expand) shows:
  - Recent branches (R3)
  - Run count link (R4)

### R3 — Recent branches in expanded view

**Frontend** `ui/src/pages/Repos.tsx`:
- When a repo card is first expanded, call
  `GET /api/repos/{name}/branches?include_remote=false` (local branches only,
  already sorted by recency via `git for-each-ref --sort=-committerdate`).
- Display the first 5 branches as a compact mono-font list with their short
  commit SHAs.
- Show "… and N more" if `total > 5`.

**Backend** — ensure `list_branches` in `repos/discovery.py` sorts by
`-committerdate` (add `--sort=-committerdate` to the `git for-each-ref` call if
not already present).

### R4 — Run count linking to filtered dashboard

**Backend** `src/orchestrator/api/routers/repos.py`:
- Add `GET /api/repos/{name}/stats` returning
  `{ "run_count": int }` — query `RunModel` where `project_path` contains the
  repo path (or use a simpler heuristic: count runs whose `project_path`
  starts with the repo path string).

**Frontend** `ui/src/pages/Repos.tsx` (expanded repo card):
- Fetch `/api/repos/{name}/stats` when card expands.
- Show: "N run(s)" as a clickable link → `/?repo=<name>` (Dashboard with repo
  filter pre-set, consistent with the existing `CreateRunModal` navigation).
- Add the `repo` query-param filter to the Dashboard if not already present (it
  may already be there via the `CreateRunModal` redirect).

---

## Group 5 — Validation Recovery Agent (V1, V2, V3)

This is the most substantial change. It introduces a `RECOVERING` task state and a
recovery-agent execution path that reuses the run's configured agent type.

### V1 — Distinguish crash from failure

**File**: `src/orchestrator/workflow/auto_verify.py`

`AutoVerifyResult` gets two new optional fields:
```python
crashed: bool = False          # True if the command raised an exception or was killed
crash_error: str | None = None # the exception message / signal description
```

`LocalAutoVerifyRunner.run_command` currently lets exceptions propagate. Wrap it
so that:
- `asyncio.TimeoutError` / `ProcessLookupError` / any `OSError` → return
  `(None, error_str)` indicating crash (exit_code=None, crash error message).
- The caller (`run_auto_verify`) populates `crashed=True` / `crash_error` when
  `exit_code` is `None`.

**File**: `src/orchestrator/workflow/auto_verify.py`

Add `has_crashes(results: list[AutoVerifyResult]) -> bool` utility.

### V2 — Trigger recovery on crash or max-attempts exceeded

**File**: `src/orchestrator/config/enums.py`
- Add `RECOVERING = "recovering"` to `TaskStatus`.

**File**: `src/orchestrator/workflow/transitions.py`
- Add `transition_to_recovering(task, failure_reason: str) -> TransitionResult`:
  - Valid only from `VERIFYING`.
  - Sets `task.status = TaskStatus.RECOVERING`.
  - Stores `failure_reason` in the current attempt's `verifier_comment`.
- Add valid transitions: `VERIFYING → RECOVERING`, `RECOVERING → BUILDING`
  (retry), `RECOVERING → COMPLETED` (skip), `RECOVERING → FAILED` (abandon),
  `RECOVERING → PENDING_USER_ACTION` (agent asks questions).
- Update `VALID_TRANSITIONS` dict accordingly.

**File**: `src/orchestrator/workflow/prompts.py`
- Add `generate_recovery_prompt(task_config, task_state, failure_context: str,
  run_config: dict) -> Prompt`:
  - System section: explains the recovery agent role, available tools
    (`request_clarification`, `complete_recovery`), and expected output.
  - User section: the task description + requirements + the `failure_context`
    (crash logs / max-attempts-exceeded summary / failed test output).

**File**: `src/orchestrator/workflow/service.py`
- Add `trigger_recovery(run_id, task_id, failure_context: str)`:
  1. Transition task `VERIFYING → RECOVERING` via `transition_to_recovering`.
  2. Generate recovery prompt via `generate_recovery_prompt`.
  3. Store it in `task.attempts[-1].builder_prompt` (reuse the field; the
     recovery prompt drives the agent just like a builder prompt).
  4. Pause the run with `pause_reason = "recovery_triggered"`.
  5. Emit a `RecoveryTriggered` event.
  6. Save and commit.
- Modify auto-verify failure handling in `submit_for_verification`:
  - If `has_crashes(post_av_results)` → call `trigger_recovery` with crash detail
    (V1 trigger).
  - If `not all_must_passed` AND `task.current_attempt >= task.max_attempts` →
    call `trigger_recovery` with max-attempts-exceeded message (V2 trigger).
  - Leave the existing "bounce back to BUILDING" path for the non-max, non-crash
    revision cycle.

### V3 — Recovery agent execution and MCP tool

**File**: `src/orchestrator/mcp/tools.py`
- Add MCP tool `complete_recovery`:
  ```
  complete_recovery(run_id, task_id, outcome: "retry"|"skip"|"abandon", notes: str)
  ```
  - `retry`: call `service.complete_recovery_retry(run_id, task_id, notes)`:
    transition `RECOVERING → BUILDING` (new attempt via `transition_to_building`),
    resume run.
  - `skip`: call `service.complete_recovery_skip(run_id, task_id, notes)`:
    transition `RECOVERING → COMPLETED` (mark task completed with notes as
    completion comment), resume run and advance to next task.
  - `abandon`: call `service.complete_recovery_abandon(run_id, task_id, notes)`:
    transition `RECOVERING → FAILED`, mark run failed if all tasks terminal.

**File**: `src/orchestrator/workflow/service.py`
- Implement `complete_recovery_retry`, `complete_recovery_skip`,
  `complete_recovery_abandon` methods as described above.

**File**: `src/orchestrator/agents/executor.py`
- In the task execution loop, when a task is in `RECOVERING` state:
  - Generate context using the stored recovery prompt (`task.attempts[-1].builder_prompt`)
    rather than calling `generate_builder_prompt`.
  - Spawn the agent with that context — same executor path as BUILDING.
  - The recovery agent will call MCP tools (`request_clarification`,
    `complete_recovery`) to drive the resolution.
- After `complete_recovery` with `retry` transitions the task to BUILDING,
  the executor resumes the normal builder loop on the next iteration.

### V1-V3 UI changes

**Frontend type updates** (`ui/src/types/runs.ts`):
- Add `'recovering'` to `TaskStatus` union.

**File**: `ui/src/lib/status.ts`:
- Add colour mapping for `recovering` (e.g. amber/orange — distinct from building
  and paused).

**File**: `ui/src/components/dashboard/RunCard.tsx` (TaskCard):
- Show "Recovering…" label for tasks in `recovering` state.

**File**: `ui/src/components/detail/TaskDetailCard.tsx`:
- Show a recovery banner (similar to the `verifier_comment` banner) when
  `task.status === 'recovering'`:
  - Show the failure context from `task.attempts[-1].verifier_comment`.
  - Show "Recovery agent is diagnosing…" when no pending questions yet.

---

## Execution Order

Execute these groups roughly in this order (dependency-aware):

1. **D1, D2** — Pure frontend label changes; zero risk, good warm-up.
2. **Q1, Q2** — Frontend-only; remove auto-popup and restyle banner.
3. **Q3** — Small backend + frontend change; always re-spawn / resume on answer.
4. **DV1** — Frontend-only; fix prompt display logic in AttemptCard.
5. **DV2** — Frontend; collapsible step sections in ActivityFeed.
6. **R2, R3, R4** — Frontend + small backend (stats endpoint).
7. **R1** — Backend (clone/symlink + delete) + frontend (add/remove modal).
8. **V1** — Backend only; crash detection in auto_verify.
9. **V2, V3** — Backend (new state, recovery trigger, MCP tool, executor changes)
   + frontend status/UI updates.

---

## Definition of Done

All 14 IDs must be individually verifiable:

- **D1**: Dashboard expanded run with multi-attempt task shows "Needs revision"
  for non-current null-outcome attempts.
- **D2**: Dashboard shows "Accepted" (not "Passed") for passed attempts.
- **Q1**: No modal appears automatically when a pending action arrives.
- **Q2**: The pending-action indicator in RunDetail is compact, no word-wrap,
  styled consistently with the rest of the UI.
- **Q3**: After answering a clarification, the agent is always re-spawned; if
  the run was paused it is resumed first.
- **DV1**: In the RunDetail Prompts section, both builder and verifier prompts
  are visible for a task that has completed verification (or is currently being
  verified).
- **DV2**: RunDetail tasks are grouped in collapsible step sections with headers;
  completed steps are collapsed by default.
- **R1**: "Add Repository" button clones a URL repo or symlinks a path into
  repos_dir; "Remove" deletes it.
- **R2**: Clicking a repo card expands it.
- **R3**: Expanded card shows the 5 most recent local branches.
- **R4**: Expanded card shows a run count that is a clickable link to the
  dashboard filtered by that repo.
- **V1**: A validation script that throws an unhandled exception is recorded as
  `crashed=True` (not just `passed=False`) in AutoVerifyResult.
- **V2**: When auto-verify crashes or max attempts are exceeded, the task
  transitions to RECOVERING, the run is paused with reason
  `"recovery_triggered"`, and a recovery prompt is stored.
- **V3**: The recovery agent (spawned with the existing agent type) can call
  `complete_recovery` to retry/skip/abandon, and can call
  `request_clarification` to ask the user questions; answering resumes the run
  and re-spawns the recovery agent.

---

## Notes for Implementation Agent

- Follow all constraints in AGENTS.md: no mocking in tests, no global state,
  async by default, Pydantic for all data, explicit error types.
- Run `uv run pytest` after each group and fix failures before moving to the next.
- Run `uv run pyright` and `uv run ruff check .` after backend changes.
- For frontend changes, run `cd ui && npx tsc --noEmit` to catch type errors.
- Do NOT skip any ID. Before finishing, explicitly confirm each ID in the
  registry is addressed.
