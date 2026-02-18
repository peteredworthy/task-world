# Design Questions: UI Gaps — Wire Remaining Backend Endpoints to Frontend

## Open Questions

_(None remaining — all questions resolved.)_

---

## Resolved Questions

### Q1: Step approval — separate modal or inline block in RunDetail?

- **Context:** The existing `ApprovalModal` handles task-level approval (approve + reject, `POST /runs/{id}/tasks/{task_id}/approve` and `/reject`). Step-level approval calls `POST /api/runs/{id}/steps/{step_id}/approve` with a different payload (`HumanApprovalRequest` with `approved_by`, `comment`) and has no reject path.
- **Options:**
  1. **Separate `StepApprovalModal`** — clear separation, matches the task-level modal pattern, slightly more code
  2. **Inline block in `RunDetail.tsx`** — directly inside the step rendering, no modal overhead; simpler for a one-action flow
  3. **Extend `ApprovalModal` with a `mode` prop** — reuse existing UI, but adds conditional rendering complexity for a fundamentally different API call
- **Impact:** Affects component count and `RunDetail.tsx` complexity. High — this is the most user-visible change.
- **Priority:** High
- **Resolution:** Option 1 — Separate `StepApprovalModal` component.
- **Rationale:** Step approval has no reject path and calls a completely different endpoint. A dedicated modal keeps the semantics clean and avoids adding conditional complexity to `ApprovalModal`.
- **Resolved by:** [HUMAN] annotation (2026-02-17)

---

### Q2: Where does step approval appear in `RunDetail.tsx`?

- **Context:** `RunDetail.tsx` renders steps via `StepAccordion`. The `StepSummary` type already has `has_approval_gate` and `approval_status`. The current step accordion does not render an approval prompt.
- **Options:**
  1. Inside `StepAccordion` — approval prompt appears in the collapsible step section where the user is already looking at step details
  2. At the top of `RunDetail.tsx` as a sticky banner (similar to how task-level approval is surfaced as a pending action) — harder to miss but may feel divorced from the step context
  3. Both: a sticky pending-action banner linking down to the step, plus inline approval in the accordion
- **Impact:** UX clarity for the human-in-the-loop workflow
- **Priority:** High
- **Resolution:** Option 3 — Both a sticky pending-action banner at the top AND inline approval inside the accordion.
- **Rationale:** The banner ensures visibility (users may not have the relevant step expanded); the inline prompt provides context where the approval decision makes sense.
- **Resolved by:** [HUMAN] annotation (2026-02-17)

---

### Q3: What does the `usePendingActions` backend response include for step approval gates?

- **Context:** `usePendingActions` calls `GET /api/runs/{id}/pending-actions`. Currently it returns task-level approval and clarification actions. Step approval gates may or may not already appear in this response.
- **Options:**
  1. Step approvals are already in the response — `PendingActionsBadge` just needs to handle the new action type
  2. Step approvals are NOT in the response — either extend the backend (out of scope) or detect them client-side from `run.steps[]` where `has_approval_gate && approval_status === 'pending'`
- **Impact:** Determines whether backend work is needed or client-side detection suffices
- **Priority:** High
- **Resolution:** Backend code inspection of `src/orchestrator/api/routers/clarifications.py` confirmed step approvals are **NOT** in the `GET /api/runs/{id}/pending-actions` response. The endpoint returns only task-level `clarification` and `approval` actions. Step-level approval state is tracked separately in `StepSummary.has_approval_gate` / `StepSummary.approval_status` on the run response. Because backend work is in scope, extend `GET /api/runs/{id}/pending-actions` to also return pending step approval gates (steps where `has_approval_gate == True` and `approval_status == "pending"`).
- **Resolved by:** Backend code inspection + [HUMAN] annotation (2026-02-17)

---

### Q4: Guidance endpoint vs task prompt — what fields does `/guidance` return that `/tasks/{id}/prompt` does not?

- **Context:** `AgentGuidancePanel` currently calls `useTaskPrompt` (which hits `GET /api/runs/{id}/tasks/{task_id}/prompt`) and hardcodes MCP URL and auth token. The backend's `GET /api/runs/{id}/guidance` is described as returning an aggregate with task prompt, MCP URL, callback instructions, and expected next actions.
- **Options:**
  1. Full refactor — remove `useTaskPrompt` from `AgentGuidancePanel` entirely, use `useGuidance` as the sole data source. Cleaner but requires confirming the guidance response fields.
  2. Additive — keep `useTaskPrompt` for the prompt text, add `useGuidance` only for the new fields (expected actions, instructions)
- **Impact:** Affects `AgentGuidancePanel` complexity and data consistency.
- **Priority:** Medium
- **Resolution:** Backend code inspection reveals two distinct endpoints with different purposes:
  - **`GET /guidance`** — run-level aggregate designed for external agents polling for work. Returns: `run_id`, `task_id` (active), combined `prompt` (system+user as one string), `phase`, `mcp_url`, `expected_actions[]`. No callback instructions breakdown.
  - **`GET /tasks/{task_id}/prompt`** — task-specific endpoint returning: separated `system` + `user` prompts, `phase`, and full `CallbackInstructions` (with REST endpoint list + MCP tool descriptions).
  - **Chosen approach:** Option 2 (additive). Keep `useTaskPrompt` for the detailed separated prompts shown in the panel. Add `useGuidance` to source `mcp_url` (replacing the hardcoded value) and `expected_actions` (new display). A full refactor to guidance-only would lose the separated prompts and rich callback instructions.
- **Resolved by:** Backend code inspection + [HUMAN] annotation (2026-02-17)

---

### Q5: How should "go back to step" be triggered in `RunDetail.tsx`?

- **Context:** The `StepProgressBar` / step indicators in `RunDetail.tsx` show completed steps. Backward transitions reset task states in the target step. The API is `POST /api/runs/{id}/transition-back` with `{ target_step_index: int }`.
- **Options:**
  1. **Button on each completed step indicator** — right-click or hover reveals "Go back to this step"; minimal UI footprint
  2. **Dropdown menu on the step progress bar** — "Revert to step…" action with a picker dialog
  3. **Separate action button on `RunDetail.tsx` toolbar** — always visible but detached from the step context
- **Impact:** UX affordance and discoverability. Confirmation dialog is required regardless.
- **Priority:** Medium
- **Resolution:** Option 2 — Dropdown menu on the step progress bar with a picker dialog.
- **Rationale:** Keeps the action discoverable without cluttering every step indicator; the picker dialog naturally communicates the relative nature of the backward jump.
- **Resolved by:** [HUMAN] annotation (2026-02-17)

---

### Q6: Should `agentCancelled` replace or supplement the existing run-level cancel?

- **Context:** `WaitingIndicator` has an `onCancel` prop that currently triggers a run-level cancel. The backend also has `POST /api/runs/{id}/agent-cancelled` which signals that the external agent specifically was cancelled (distinct from cancelling the whole run).
- **Options:**
  1. **Replace** — `WaitingIndicator`'s cancel calls `agentCancelled` instead of `cancelRun`; run-level cancel is a separate action
  2. **Supplement** — `WaitingIndicator` has two buttons: "Agent stopped" (calls `agentCancelled`) and "Cancel run" (calls `cancelRun`)
  3. **Both** — call both `agentCancelled` then `cancelRun` in sequence
- **Impact:** Semantics of the cancel flow for user-managed agents
- **Priority:** Medium
- **Resolution:** Agent cancellation should transition the run to **PAUSED** (not FAILED) so the user can restart. Backend inspection shows the current `POST /api/runs/{id}/agent-cancelled` calls `service.cancel_run()` which goes to FAILED — this backend behavior needs to change. On the frontend, use Option 1: the `agentCancelled` call replaces the existing run-level cancel in `WaitingIndicator`. Intentional run termination remains via a separate "Cancel run" control. **Backend change required:** `agent-cancelled` endpoint must transition to PAUSED instead of FAILED.
- **Resolved by:** Backend code inspection + [HUMAN] annotation (2026-02-17)

---

### Q7: What is the `target_step` parameter type for `transition-back`?

- **Context:** The plan says `transitionBack(runId, { target_step })`. We need to know if `target_step` is a step ID (UUID string), a step `config_id` (string identifier from the routine), or a zero-based step index (integer).
- **Options:**
  1. Step ID (UUID from `StepSummary.id`)
  2. Step config_id (from `StepSummary.config_id`)
  3. Zero-based index
- **Impact:** Determines what data is passed from the UI to the API call
- **Priority:** High
- **Resolution:** Backend code inspection of `src/orchestrator/api/routers/runs.py` confirms **Option 3 — zero-based integer index**. The `BackwardTransitionRequest` schema has `target_step_index: int`, and the service passes it directly as an array position. The frontend should pass the index of the target step in `run.steps[]`. Router docstrings should be updated to document this parameter clearly.
- **Resolved by:** Backend code inspection + [HUMAN] annotation (2026-02-17)

---

### Q8: Does the SSE settings toggle already exist?

- **Context:** The idea doc listed "Activity SSE Streaming (Settings Integration)" as work needed, implying the toggle was missing.
- **Resolution:** The toggle **already exists** in `ui/src/components/SettingsModal.tsx` — a radio group for `activityStreamMode` (`'sse'` | `'polling'`) is implemented and wired to `useSettings`. What is still missing is a connection status indicator in the activity feed when SSE mode is active.
- **Impact:** Step 4 (SSE settings) scope is reduced to just adding the `isConnected` status indicator — the toggle itself is done.
- **Resolved by:** Code inspection during planning (2026-02-17)
