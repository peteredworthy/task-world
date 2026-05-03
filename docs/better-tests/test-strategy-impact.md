# Test Strategy Impact Report — Priorities 3 & 4

Generated from implementation of `test-strategy-improvements.md` priorities 3 and 4.

---

## What was implemented

### Priority 3 — WS `processEvent` Unit Tests

**File:** `ui/tests/hooks/useWebSocket.test.tsx`

The file already existed with 13 tests from the earlier bug-fix pass. This implementation added 11 new tests across two new `describe` blocks:

**Added: explicit `checklist_gate_evaluated` and `grades_evaluated` coverage**
- `checklist_gate_evaluated` invalidates `run` cache
- `checklist_gate_evaluated` with `task_id` invalidates the specific task
- `grades_evaluated` invalidates `run` cache
- `grades_evaluated` with `task_id` invalidates the specific task

Both event types were handled by the same code branch as `task_status_changed` but had zero explicit tests. A future refactor that accidentally removed them from the branch would have been invisible.

**Added: "no extra invalidations" guard suite (5 tests)**

For each event type, asserts the *exact* number of `invalidateQueries` calls:

| Event type | Expected calls | Keys |
|---|---|---|
| `approval_requested` | 2 | `activity`, `pending-actions` |
| `run_status_changed` | 3 | `activity`, `run`, `runs` |
| `task_status_changed` (no task_id) | 2 | `activity`, `run` |
| `task_status_changed` (with task_id) | 3 | `activity`, `run`, `task` |
| `clarification_responded` (no task_id) | 1 | `activity` only |

Without these guards, adding an extra `invalidateQueries` call (e.g. also invalidating `runs` on `approval_requested`) would silently cause over-fetching — degraded performance with no failing test.

**Total test count after:** 24 tests (was 13)

---

### Priority 4 — Playwright State Transition Smoke Tests

**File:** `ui/tests/e2e/state-transitions.spec.ts` (new file, 380 lines)

10 tests covering 6 scenarios. All pass in ~6s (1 worker, Chromium).

| Test | What it verifies |
|---|---|
| `paused_server_shutdown_shows_banner` | pause_reason → correct banner text |
| `paused_gate_blocked_shows_banner` | pause_reason → correct banner text |
| `paused_agent_not_available_shows_banner` | pause_reason → correct banner text |
| `stopping_state_has_no_pause_resume_abort_buttons` | `stopping` status hides all action buttons |
| `stuck_run_shows_run_blocked_warning` | `isRunStuck()` produces the "Run blocked" banner |
| `active_run_shows_pause_button_not_resume` | active status button logic |
| `paused_run_shows_resume_button_not_pause` | paused status button logic |
| `approval_requested_ws_event_shows_pending_actions_banner` | WS frame → cache invalidate → refetch → banner |
| `pending_action_auto_opens_approval_modal_on_load` | `autoOpenedRef` auto-open fires on load |
| `second_pending_action_auto_opens_after_first_dismissed` | `autoOpenedRef` key rotates for new action |

**Technique:** `page.routeWebSocket()` (Playwright 1.48+) intercepts the WebSocket connection. Tests that need WS injection capture the route handle and call `ws.send()` directly, triggering React Query's `invalidateQueries` and forcing a real refetch through the mocked HTTP routes. No real server needed.

---

## What was discovered during implementation

**1. The existing useWebSocket.test.tsx was already comprehensive for event routing.**
The "Fix 7 state/UI bugs" commit had already added the core `processEvent` tests. Priority 3's main gap was the explicit group-member tests (`checklist_gate_evaluated`, `grades_evaluated`) and the count-guard assertions.

**2. `clarification_responded` without `payload.task_id` fires exactly 1 invalidation (activity only).**
This is a non-obvious behaviour: if the backend emits `clarification_responded` without a `task_id`, no cache is updated except the activity feed. This was untested and could silently break — the count guard now documents and enforces it.

**3. The `autoOpenedRef` fix is already in the codebase and works correctly.**
The ref stores a `task_id:action_type` key, not a boolean. A second pending action with a different `task_id` correctly auto-opens. Test 10 (`second_pending_action_auto_opens_after_first_dismissed`) confirms the non-regressed state.

**4. `page.routeWebSocket()` in Playwright 1.48+ is the correct tool for WS injection.**
Earlier approaches (`page.addInitScript` to monkey-patch `window.WebSocket`) would have been fragile. The native API cleanly intercepts WS connections without touching the browser environment.

**5. LIFO route ordering is critical for dynamic test state.**
Adding a `page.route()` for `pending-actions` *after* `setupRoutes()` overrides the static handler from setup (Playwright evaluates routes in LIFO order). This lets tests change the pending-actions response mid-test without requiring a separate "update route" API.

---

## How it changes the speed of testing

| Scenario | Before | After |
|---|---|---|
| Verify approval_requested invalidates the right cache keys | Manual inspection of `useWebSocket.ts` | `vitest run` — ~26ms for the processEvent suite |
| Detect extra cache invalidation added by accident | Not detectable (no count guard) | Fail immediately on next vitest run |
| Verify paused run shows correct banner | Full local dev server + manual browser test | `playwright test` — ~400ms per banner variant |
| Verify stopping state hides action buttons | Manual click-through after setting up a run in that state | ~330ms automated |
| Verify WS event reaches the UI | Manual: trigger backend event, watch browser network tab, observe UI | ~430ms automated |
| Verify auto-open modal on load | Manual: create a run with a pending action, reload, observe | ~430ms automated |

**Overall:** The scenarios above were previously untestable without a running backend. They now run fully offline in under 7 seconds total (10 tests × ~600ms average).

---

## Classes of issue now protected against

### 1. Cache invalidation drift (Priority 3 — count guards)
**Pattern:** Developer adds an extra `qc.invalidateQueries(...)` call inside a `processEvent` branch, causing over-fetching.
**Protection:** The exact-count guards fail immediately. No silent performance regression can be introduced without a failing test.

### 2. Missing event routing (Priority 3 — `checklist_gate_evaluated`, `grades_evaluated`)
**Pattern:** A refactor extracts `task_status_changed` handling into a shared function but accidentally leaves `checklist_gate_evaluated` out of the branch.
**Protection:** Four tests explicitly assert the invalidation behaviour for these two event types.

### 3. Pause banner regression (Priority 4 — banner tests)
**Pattern:** A rename of a `pause_reason` value in `getPauseReasonMessage()` silently produces `"Paused (old_name)"` instead of the intended message.
**Protection:** Three tests assert exact banner text for `server_shutdown`, `gate_blocked`, and `agent_not_available`. Wrong text → test failure.

### 4. Status badge / button logic regression (Priority 4 — stopping / active / paused tests)
**Pattern:** A change to the button rendering conditions (`run.status === 'active'`) accidentally shows a Pause button on a stopping run.
**Protection:** `stopping_state_has_no_pause_resume_abort_buttons` explicitly asserts all three buttons are absent. The `active/paused` button tests guard the inverse.

### 5. `isRunStuck()` render path untested (Priority 4 — stuck run test)
**Pattern:** A refactor of the stuck-run banner condition silently removes the warning. Previously had zero test coverage (strategy doc bug 7).
**Protection:** `stuck_run_shows_run_blocked_warning` loads a run with a failed-at-max-attempts task and asserts the banner renders.

### 6. WS event does not reach query cache (Priority 4 — WS injection test)
**Pattern:** A change to `processEvent` removes the `approval_requested` invalidation, or moves the logic to a branch that's never entered.
**Protection:** `approval_requested_ws_event_shows_pending_actions_banner` injects a real WS frame and asserts the banner appears within 3 seconds. The entire stack (WS → processEvent → invalidateQueries → HTTP refetch → React render) must be intact.

### 7. `autoOpenedRef` auto-open regression (Priority 4 — auto-open tests)
**Pattern:** A refactor changes `autoOpenedRef` from per-action-key tracking back to a boolean, so only the first pending action ever auto-opens.
**Protection:** Two tests: one confirms auto-open fires on load; one confirms a second different action auto-opens after the first is dismissed. Both require the key-comparison logic to be intact.

---

## Summary

| Item | Tests added | Bugs protected | Speed |
|---|---|---|---|
| Priority 3: WS event routing unit tests | +11 (total 24) | Cache invalidation drift, missing event branches | <30ms per run |
| Priority 4: Playwright state transition tests | +10 (new file) | Pause banners, button logic, stuck-run, WS→UI pipeline, auto-open | ~6s total |
| **Total** | **+21 tests** | **7 distinct bug classes** | — |
