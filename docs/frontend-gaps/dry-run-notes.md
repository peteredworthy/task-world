# Dry-Run Simulation Notes: Close All 21 Frontend Gaps

## Overview

This document captures the results of simulating execution across all 8 implementation steps (21 gaps + 1 new gap). Each step is evaluated for assumptions, expected outputs, blockers, and remediation strategies.

---

## Step 1: Step-Level Approval UI (Gap 1 — HIGH)

### Assumptions
- Backend `POST /api/runs/{id}/steps/{step_id}/approve` endpoint exists and is functional (verified: present in `runs.py` at line ~599+)
- `ApprovalModal.tsx` exists as a reference pattern for building `StepApprovalModal`
- Pending actions API (`GET /api/runs/{id}/pending-actions`) returns step-level approval actions with a distinguishable `type` field (e.g. `step_approval` vs `task_approval`)

### Expected Outputs
- New file: `ui/src/components/detail/StepApprovalModal.tsx`
- Modified: `ui/src/types/index.ts` (add `StepApprovalRequest`)
- Modified: `ui/src/hooks/useApi.ts` (add `useApproveStep` mutation)
- Modified: `ui/src/pages/RunDetail.tsx` (detect step_approval pending actions, render modal)
- `npx tsc --noEmit` passes

### Blockers & Gaps
1. **Pending action type discrimination** — The pending actions response must distinguish step-level from task-level approvals. If the `pending-actions` endpoint returns a flat list without a `type` field differentiating step vs task approval, the frontend cannot route correctly.
   - **Remediation:** Inspect the `pending-actions` response schema. If missing, either (a) add a `kind` discriminator field to the backend response, or (b) infer from the presence of `step_id` vs `task_id` in the action payload. The frontend exploration confirms pending actions include both clarifications and approvals — verify the shape includes step identification.

2. **Step ID availability** — RunDetail must know which step requires approval. The step approval endpoint needs `step_id` in the URL path.
   - **Remediation:** The pending action payload should include `step_id`. Verify the backend's `PendingAction` model includes this field.

### Verdict: **EXECUTABLE** with minor verification needed on pending action schema shape.

---

## Step 2: Branch Status + Back-Merge (Gaps 2, 3 — HIGH)

### Assumptions
- Backend `GET /api/runs/{id}/branch-status` endpoint exists — **NOT VERIFIED**. The runs router has `merge-back` but branch-status is not confirmed as a separate endpoint.
- Backend `POST /api/runs/{id}/back-merge` exists (verified: `merge-back` endpoint present in runs router)
- WebSocket events include `run_status_changed` for triggering branch status refetch
- BranchSelector.tsx exists as a related but different component (branch selection during run creation, not status display)

### Expected Outputs
- New file: `ui/src/types/branches.ts`
- New file: `ui/src/components/detail/BranchStatusPanel.tsx`
- New file: `ui/src/components/detail/BackMergeDialog.tsx`
- Modified: `ui/src/hooks/useApi.ts` (add `useBranchStatus`, `useBackMerge`)
- Modified: `ui/src/pages/RunDetail.tsx` (mount both components)
- `npx tsc --noEmit` passes

### Blockers & Gaps
1. **Branch status endpoint uncertainty** — The plan references `GET /api/runs/{id}/branch-status` but this endpoint was not confirmed in the backend router exploration. The existing `merge-back` (aliased as `back-merge`) endpoint exists, but a dedicated branch-status GET may be missing.
   - **Remediation:** Check if `GET /api/runs/{id}/branch-status` exists in the runs router. If missing, this is a **backend gap** that violates the "all work is frontend-only" scope assumption. Fallback: derive branch status from the run detail response if it includes branch metadata (ahead/behind counts, conflict status). Alternatively, request the backend team add this endpoint.

2. **Endpoint naming discrepancy** — Plan says `back-merge` but backend uses `merge-back`. Need to use the correct endpoint name.
   - **Remediation:** Use the actual backend endpoint path: `POST /api/runs/{id}/merge-back`. The API client likely already has this wired (confirmed: `mergeBack` exists in `client.ts`).

3. **WebSocket event names** — Plan assumes `run_status_changed` event triggers branch status refetch. Need to confirm the actual WebSocket event names emitted by the backend.
   - **Remediation:** Check WebSocketContext.tsx for existing event handling patterns. The existing codebase uses WebSocket for real-time updates with known event types. Align event name with actual backend emissions.

### Verdict: **PARTIALLY BLOCKED** — Branch status endpoint existence must be confirmed. If missing, either a backend change is needed (out of scope) or the feature must derive status from existing data.

---

## Step 3: Merge Strategy + Clarification Context + Gate Types (Gaps 4, 7, 8 — MEDIUM)

### Assumptions
- Step 2 is complete (BackMergeDialog exists to add strategy picker to)
- `merge-back` endpoint accepts a `strategy` parameter (squash/merge/rebase) — the `mergeBack` API client method likely already supports this
- `ClarificationModal.tsx` exists and renders clarification questions — verified, it has full Q&A UI
- Clarification question objects have a `context` field — needs verification
- Pending actions include a `gate_type` field

### Expected Outputs
- New file: `ui/src/components/detail/MergeStrategyPicker.tsx`
- New file: `ui/src/components/GateTypeBadge.tsx`
- Modified: `ui/src/components/detail/BackMergeDialog.tsx` (add strategy picker)
- Modified: `ui/src/components/run/CreateRunModal.tsx` (add strategy in advanced config)
- Modified: `ui/src/components/detail/ClarificationModal.tsx` (render context)
- Modified: `ui/src/components/dashboard/PendingActionsBadge.tsx` (show gate type)
- `npx tsc --noEmit` passes

### Blockers & Gaps
1. **Clarification `context` field** — The plan assumes clarification questions include a `context` field. If the backend model doesn't include this, the ClarificationModal enhancement has nothing to render.
   - **Remediation:** Check the `ClarificationQuestion` Pydantic model in the backend. If `context` is absent, this sub-gap becomes a backend issue. Graceful degradation: skip rendering when context is null/undefined.

2. **Gate type in pending actions** — PendingActionsBadge needs gate type info. The pending actions response may not include gate type.
   - **Remediation:** Verify pending actions schema includes gate type. If not, the badge can show a generic "Approval needed" without type discrimination. This is a cosmetic degradation, not a blocker.

### Verdict: **EXECUTABLE** — Hard dependency on Step 2 completion. Clarification context and gate type are gracefully degradable.

---

## Step 4: Attempt Cost + Auto-Verify Output + Step Progress Text (Gaps 5, 6, 9 — MEDIUM)

### Assumptions
- Attempt data includes `tokens_read`, `tokens_write`, and cost fields — verified: MetricsBar already displays these
- Auto-verify events in the activity feed include stdout/stderr content
- Run data includes step progress information (current step index, total steps) — verified: StepTimeline already uses this data

### Expected Outputs
- New file: `ui/src/components/detail/AttemptMetrics.tsx`
- New file: `ui/src/components/detail/AutoVerifyOutput.tsx`
- Modified: `ui/src/components/detail/AttemptHistory.tsx`
- Modified: `ui/src/components/detail/ActivityFeed.tsx`
- Modified: `ui/src/components/dashboard/RunCard.tsx`
- `npx tsc --noEmit` passes

### Blockers & Gaps
1. **Auto-verify event payload** — The plan assumes auto-verify events carry stdout/stderr. Need to confirm the event payload structure in the activity stream.
   - **Remediation:** Check the activity event types for auto-verify. If stdout/stderr aren't in the event payload, check if there's a separate endpoint to fetch auto-verify output (e.g., from attempt logs). Fallback: link to the logs viewer for auto-verify output.

2. **Cost calculation rate** — AttemptMetrics uses a "constant rate multiplier" for token→cost conversion. The rate needs to be defined (or configurable).
   - **Remediation:** Use a reasonable default rate constant. Can be made configurable later via settings. This is not a blocker.

### Verdict: **EXECUTABLE** — Auto-verify output availability in events needs verification but has fallback paths.

---

## Step 5: History Page + Live Guidance (Gaps 10, 11 — MEDIUM)

### Assumptions
- History.tsx is currently a placeholder ("Coming soon") — verified
- Runs listing endpoint (`GET /api/runs`) supports filtering by status (completed/failed) — verified: RunFilters.tsx already filters by status
- `GET /api/runs/{id}/guidance` endpoint exists — verified in backend router
- AgentGuidancePanel.tsx exists — verified, currently used for user-managed agents

### Expected Outputs
- New file: `ui/src/types/guidance.ts`
- Modified: `ui/src/hooks/useApi.ts` (add `useGuidance`)
- Modified: `ui/src/pages/History.tsx` (complete rewrite)
- Modified: `ui/src/components/guidance/AgentGuidancePanel.tsx`
- `npx tsc --noEmit` passes

### Blockers & Gaps
1. **Pagination pattern** — History page needs cursor-based pagination. The existing `useActivity` hook uses cursor pagination — this is a good reference pattern.
   - **Remediation:** Follow the `useActivity` pagination pattern. No blocker.

2. **Date range filtering** — The runs API may not support date range query parameters.
   - **Remediation:** Check if `GET /api/runs` accepts `created_after`/`created_before` params. If not, either (a) filter client-side for small datasets, or (b) note as a backend enhancement. Client-side filtering is acceptable for MVP.

3. **Guidance response shape** — Need to verify the guidance endpoint returns `prompt`, `phase`, and `expected_actions` fields.
   - **Remediation:** Check the GuidanceResponse schema in the backend. The AgentGuidancePanel already consumes some guidance data — align with existing shape.

### Verdict: **EXECUTABLE** — Well-supported by existing patterns and verified endpoints.

---

## Step 6: Routine Detail + Agents Flow + Revision Viz (Gaps 12, 13, 14 — LOW)

### Assumptions
- RoutineLibrary.tsx exists with routine listing — verified
- Agents.tsx exists with agent listing — verified
- CreateRunContext.tsx exists for modal state — verified
- React Router navigation state can pass `prefillAgentType`
- Routine detail data includes gate types, auto-verify commands, requirement priorities

### Expected Outputs
- Modified: `ui/src/pages/RoutineLibrary.tsx` (enrich detail view)
- Modified: `ui/src/pages/Agents.tsx` (add "Create run" button)
- Modified: `ui/src/context/CreateRunContext.tsx` (accept prefill)
- Modified: `ui/src/components/detail/AttemptHistory.tsx` (add connectors)
- `npx tsc --noEmit` passes

### Blockers & Gaps
1. **Routine detail data completeness** — The routine API response must include gate types, auto-verify commands, and requirement priorities. Need to verify the `GET /api/routines/{id}` response shape.
   - **Remediation:** Check RoutineConfig model fields. The routine YAML schema defines gates and auto-verify — these should be in the API response. If any fields are missing from the API serialization, graceful degradation applies (omit sections with missing data).

2. **Navigation state for agent pre-fill** — Passing state via React Router navigation (`useNavigate` with state) works but is fragile (state lost on page refresh).
   - **Remediation:** Plan already accounts for this: "Navigation state loss handled gracefully → modal opens without pre-fill." No blocker.

### Verdict: **EXECUTABLE** — Low risk, all modifications to existing files with graceful degradation.

---

## Step 7: Grade Threshold + Blocked State + Elapsed Time (Gaps 15, 16, 17 — LOW)

### Assumptions
- Verification results include grade threshold data (threshold value, scores, critical failures)
- StatusBadge.tsx supports variant-based rendering — verified
- MetricsBar.tsx exists — verified
- Run data includes `started_at` timestamp for elapsed time calculation

### Expected Outputs
- New file: `ui/src/components/detail/GradeThresholdExplainer.tsx`
- New file: `ui/src/components/detail/ElapsedTimer.tsx`
- Modified: `ui/src/components/detail/ChecklistTable.tsx`
- Modified: `ui/src/components/StatusBadge.tsx`
- Modified: `ui/src/pages/RunDetail.tsx`
- Modified: `ui/src/components/detail/MetricsBar.tsx`
- `npx tsc --noEmit` passes

### Blockers & Gaps
1. **Grade threshold data availability** — GradeThresholdExplainer needs threshold value, average score, and critical failure list. This data must be available in the task/checklist response.
   - **Remediation:** Check the verification/grading response shape. The `grades.py` module performs threshold evaluation — its output should include these values. If not exposed via API, the explainer shows a generic "Verification failed" message.

2. **Blocked-on-human detection** — Determining "blocked on human" requires checking: run is ACTIVE AND has pending human actions (approvals or clarifications).
   - **Remediation:** RunDetail already fetches pending actions. Combine run status + pending actions count > 0 to derive blocked state. No blocker.

### Verdict: **EXECUTABLE** — Straightforward implementations with clear fallback paths.

---

## Step 8: Validation + Env Files + Transitions + Dashboard WS (Gaps 18, 19, 20, 21 — LOW)

### Assumptions
- `POST /api/routines/validate` endpoint exists — **NOT VERIFIED**
- Env file endpoints exist (`GET /api/runs/{id}/env-files`, snapshots, revert, copy-back) — verified
- StepTimeline can be extended for backward-jump visualization
- A dashboard-level WebSocket/SSE endpoint exists or can be created

### Expected Outputs
- New file: `ui/src/types/routines.ts` (validation types)
- New file: `ui/src/types/envfiles.ts`
- New file: `ui/src/components/EnvFileTemplates.tsx`
- New file: `ui/src/components/run/EnvFileOverrides.tsx`
- Modified: `ui/src/hooks/useApi.ts` (5 new hooks)
- Modified: `ui/src/pages/RoutineLibrary.tsx` (validate button)
- Modified: `ui/src/components/run/CreateRunModal.tsx` (env overrides)
- Modified: `ui/src/components/dashboard/StepTimeline.tsx` (backward jumps)
- Modified: `ui/src/pages/Dashboard.tsx` (WebSocket connection)
- `npx tsc --noEmit` passes

### Blockers & Gaps
1. **Routine validation endpoint** — `POST /api/routines/validate` is referenced but not confirmed in the backend. This is a potential backend gap.
   - **Remediation:** Check the routines router for a validate endpoint. If missing, this is a **backend gap** requiring either (a) backend implementation (out of scope), or (b) client-side YAML validation as a fallback (parse YAML, check required fields). Flag for backend team.

2. **Dashboard WebSocket/SSE endpoint** — The plan acknowledges this may need a new backend endpoint for aggregate run status updates. CONFLICTS.md flags this as an open issue.
   - **Remediation:** Three-tier approach:
     - **Preferred:** Use existing SSE `/api/runs/{id}/activity/stream` per-run if available
     - **Fallback 1:** Establish WebSocket connections to individual active runs
     - **Fallback 2:** Keep current 10s polling (existing behavior) with a console warning
   - This is a **known limitation**. The frontend can implement the WebSocket client with graceful fallback to polling. Not a hard blocker.

3. **Env file templates vs run-scoped** — The plan describes "base templates in config area" but env file endpoints are run-scoped (`/api/runs/{id}/env-files`). There may not be a global template endpoint.
   - **Remediation:** Per CONFLICTS.md, this is flagged. Fallback: implement only the run-scoped env file management (viewing current env files, snapshots, revert) and skip the global template management UI. The CreateRunModal can still show env file override inputs based on the routine's declared env files.

4. **Non-linear step transition data** — StepTimeline needs to know about backward jumps. This requires step transition history in the run data.
   - **Remediation:** Check if the step/task status history includes transition direction. If not available, visualize based on attempt count (attempt > 1 implies a revision loop / backward transition). CSS-only approach keeps this low-risk.

### Verdict: **PARTIALLY BLOCKED** — Routine validation endpoint and dashboard WebSocket are potential backend gaps. Env file template scope needs clarification. All have viable fallback strategies.

---

## Cross-Cutting Concerns

### Assumption: "All work is frontend-only"

**Reality check:** The simulation identifies **3 potential backend gaps** that conflict with the "frontend-only" scope:

| Gap | Backend Issue | Severity | Fallback |
|-----|--------------|----------|----------|
| Branch status endpoint | `GET /api/runs/{id}/branch-status` unconfirmed | Medium | Derive from run detail data |
| Routine validation endpoint | `POST /api/routines/validate` unconfirmed | Low | Client-side YAML validation |
| Dashboard aggregate WebSocket | No aggregate endpoint exists | Low | Keep 10s polling (current behavior) |

### Assumption: "Backend APIs already exist for all gaps"

**Partially true.** Most endpoints are confirmed. The three above need verification. The env file endpoints exist but are run-scoped, not template-scoped as the plan envisions.

### TypeScript Safety

All steps require `npx tsc --noEmit` to pass. Risk: adding new types and hooks may introduce import cycles or type mismatches with backend response shapes. Remediation: define types based on actual API responses (inspect backend Pydantic models), not assumptions.

### Testing Strategy

The plan relies primarily on `npx tsc --noEmit` as auto-verification. Manual browser testing is listed but not automated. No Vitest component tests are mentioned.

**Recommendation:** Add at minimum:
- Type-level tests (ensure API response types match Pydantic models)
- Smoke-level integration tests for critical flows (step approval, back-merge)

---

## Summary: Gap Remediation Table

| # | Gap | Step | Status | Blocker | Remediation |
|---|-----|------|--------|---------|-------------|
| 1 | Step approval UI | 1 | Executable | Pending action schema shape | Verify discriminator field; infer from step_id presence |
| 2 | Branch status display | 2 | Partially blocked | Branch status endpoint unconfirmed | Derive from run detail or request backend endpoint |
| 3 | Back-merge UI | 2 | Executable | Endpoint naming (`merge-back` not `back-merge`) | Use actual endpoint name from client.ts |
| 4 | Merge strategy selection | 3 | Executable | None | Strategy param likely already supported |
| 5 | Per-attempt cost breakdown | 4 | Executable | Cost rate constant undefined | Use reasonable default, make configurable later |
| 6 | Auto-verify output | 4 | Executable | Event payload shape unverified | Check event types; fallback to logs viewer link |
| 7 | Clarification context | 3 | Executable | Context field unverified in model | Graceful degradation (skip if null) |
| 8 | Gate type indication | 3 | Executable | Gate type in pending actions unverified | Generic badge fallback |
| 9 | Step progress text | 4 | Executable | None | StepTimeline data already available |
| 10 | History page | 5 | Executable | Date range filtering may need client-side | Client-side filter acceptable for MVP |
| 11 | Live guidance | 5 | Executable | None | Endpoint verified, panel exists |
| 12 | Rich routine inspection | 6 | Executable | Routine detail completeness unverified | Graceful degradation |
| 13 | Agents → CreateRun flow | 6 | Executable | None | Navigation state with graceful fallback |
| 14 | Revision loop visualization | 6 | Executable | None | CSS-only connectors, low risk |
| 15 | Grade threshold explanation | 7 | Executable | Threshold data availability unverified | Generic "failed" message fallback |
| 16 | Blocked-on-human state | 7 | Executable | None | Derived from status + pending actions |
| 17 | Elapsed time | 7 | Executable | None | Standard setInterval pattern |
| 18 | Routine validation UI | 8 | Partially blocked | Validate endpoint unconfirmed | Client-side YAML parsing fallback |
| 19 | Env file management | 8 | Partially blocked | Global templates vs run-scoped mismatch | Run-scoped only for MVP |
| 20 | Conditional step transitions | 8 | Executable | Transition history data unverified | Infer from attempt counts |
| 21 | Dashboard real-time | 8 | Partially blocked | No aggregate WS endpoint | Polling fallback (current behavior) |
| 22 | Design-question UI | — | Not planned | Requires further design | Deferred; noted in CONFLICTS.md |

---

## Recommendations Before Execution

1. **Verify backend response schemas** for: pending actions (step vs task discrimination), branch status endpoint, clarification context field, gate type in actions, auto-verify event payload, grade threshold data, routine validation endpoint.

2. **Resolve the 3 backend gaps** before starting Steps 2 and 8, or commit to fallback strategies:
   - Branch status: derive from run detail metadata
   - Routine validation: client-side YAML parsing
   - Dashboard WebSocket: keep polling

3. **Establish the env file scope**: run-scoped management only (confirmed endpoints) vs global templates (unconfirmed). Recommend run-scoped for MVP.

4. **Add Gap 22 (Design-question UI)** to a future milestone — it requires further design work and is not covered by any current step.

5. **Consider adding Vitest component tests** for the 3 HIGH-severity gaps (Steps 1-2) to provide automated verification beyond TypeScript compilation.

---

## Comparison vs Intent

| Intent Requirement | Coverage | Notes |
|-------------------|----------|-------|
| All 3 HIGH gaps closed | Steps 1-2 | Branch status has backend uncertainty |
| All 8 MEDIUM gaps closed | Steps 3-5 | Fully covered |
| All 10 LOW gaps closed | Steps 6-8 | 3 sub-features have backend gaps with fallbacks |
| No TypeScript errors | Every step | `npx tsc --noEmit` as gate |
| Existing functionality unbroken | Implicit | No automated regression test plan — risk |
| pre-commit passes | Every step | Linting/formatting gates |

The plan covers all 21 original gaps plus identifies 1 new gap (Gap 22). Execution is feasible with the documented fallback strategies for the 4 partially-blocked items.
