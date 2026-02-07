# UI Review: Gaps Between Specification and Implementation

This document compares the current UI implementation against `22-UI-SPECIFICATION.md`, the reference screenshots (`01-04.png`), and the mockup JSX (`orchestrator-ui-mockup.jsx`). Items are categorized by severity and whether they require frontend-only fixes or backend changes.

---

## Legend

- **Severity**: `P0` = breaks core workflow or data misrepresentation, `P1` = notable UX gap, `P2` = polish/nice-to-have
- **Type**: `frontend` = UI-only fix, `backend` = needs API/engine change, `both` = needs both

---

## 1. Data Model & Backend Gaps

These issues stem from the backend not providing data that the spec assumes exists.

### G-01: Step progression not tracked (P0, backend) — RESOLVED

**Spec says:** Steps have statuses (`pending`, `in_progress`, `completed`, `failed`, `skipped`). `current_step_index` advances as steps complete.

**Fix applied:** `check_step_progression()` in `workflow/transitions.py` marks steps as completed and advances `current_step_index` when all tasks in a step reach terminal status. Called from `engine.py:complete_verification()`. `StepCompleted` events are emitted for each newly completed step. Event replay in `db/recovery.py` reconstructs step progression from these events. Tests: `test_step_progression_advances_index`, `test_complete_verification_advances_step`.

### G-02: Run status not auto-transitioning to COMPLETED (P0, backend) — RESOLVED

**Spec says:** Run status should be `completed` when all tasks across all steps finish successfully.

**Fix applied:** `check_run_completion()` in `workflow/transitions.py` auto-transitions the run to COMPLETED (all tasks passed) or FAILED (any task failed) when all steps are done. Called from `engine.py:complete_verification()` after step progression check. A `RunStatusChanged` event is emitted. Tests: `test_run_auto_completes_when_all_steps_done`, `test_run_auto_fails_when_task_fails`.

### G-03: Task title not exposed in summary responses (P1, both) — RESOLVED

**Spec says** (Section 3.3): Task cards show the task title (e.g., "Write Design Doc", "Implement Data Models").

**Status:** Already working. The factory copies `title=task_config.title` in `state/factory.py:43`. Both `TaskSummary` in the backend schema and frontend types include a `title` field. Both TaskCard components use `task.title || task.config_id` as fallback.

### G-04: Attempt grades not structured as three-tier GradeSet (P1, backend) — RESOLVED

**Spec says** (Section 12, `Attempt` interface): Each attempt has a `grades: GradeSet` with `required`, `expected`, and `optional` arrays.

**Actual (before fix):** Grades lived on `ChecklistItem` objects at the task level, not per-attempt. No per-attempt grade snapshot.

**Fix applied:** Each `Attempt` now has a `grade_snapshot: list[GradeSnapshotItem]` field that captures `{req_id, grade, grade_reason}` for every checklist item at the moment verification completes. The `GradesEvaluated` event also includes `grade_details` so event replay reconstructs snapshots correctly. The API's `AttemptSchema` exposes `grade_snapshot` to the frontend. The UI can now render per-attempt grade badges (e.g., `[F][D][-]` for attempt 1, `[A][A][B]` for attempt 2).

**Note:** The data model uses a flat list of `{req_id, grade, grade_reason}` rather than the spec's three-tier `GradeSet` with `required/expected/optional` arrays. The frontend can group by priority using the checklist metadata already available from the task detail endpoint.

### G-05: No version/git SHA on routine summaries (P1, backend)

**Spec says** (Section 4.3): Routine cards show version badge (e.g., "v1.2", "v2.0", "beta").

**Actual:** `RoutineSummary` has no `version` or `git_sha` field. The backend `RoutineConfig` model doesn't have a version field either — versioning is planned for Phase 7 (git integration).

**Impact:** Routine cards in the library are missing the version badge shown in the spec.

**Fix:** Defer to Phase 7, or add a static `version` field to routine YAML schema.

### G-06: No estimated cost field from backend (P2, frontend)

**Spec says** (Section 3.2): Metrics bar shows "EST. COST".

**Actual:** The MetricsBar component estimates cost client-side using hardcoded rates ($3/1M input, $15/1M output). This is a reasonable approximation but not backed by real cost data.

**Status:** Acceptable as-is. Could be improved if the backend tracked actual model pricing.

---

## 2. Frontend Feature Gaps

These can be fixed purely in the UI code.

### G-07: No three-tier grade row in task cards (P1, frontend) — RESOLVED

**Spec says** (Section 2.3, 11.1): Task cards in both dashboard expanded view and run detail show grade badges in a `[Required | Expected | Optional]` layout, with letter grades colored by value.

**Fix applied:** Backend `TaskSummary` now includes `grade_summary: list[GradeSummaryItem]` populated from checklist items. A new `CompactGradeRow` component renders sorted compact `[A][B][-]` grade badges (5x5px, sorted by priority). Integrated into both `RunCard.tsx` inline TaskCard and `detail/TaskCard.tsx`.

### G-08: No retry stacking in task cards (P1, frontend) — RESOLVED

**Spec says** (Section 2.3, 11.2): Retry attempts stack vertically within the same task card. Each retry row shows its own grade badges. Active retry shows "Building..." or "Retrying..." text.

**Fix applied:** Backend `TaskSummary` now includes `attempts_summary: list[AttemptOutcome]` populated from task attempts. When a task has multiple attempts, the dashboard TaskCard renders stacked rows with attempt number and outcome indicator (Passed/Revision/Failed/Building...). Outcome helpers extracted to `lib/outcome.ts` for reuse between `InspectorPanel` and `RunCard`.

### G-09: No activity status text on active tasks (P2, frontend)

**Spec says** (Section 2.3): Active runs show contextual status like "Generating Code...", "Retrying...".

**Actual:** Active tasks show a pulsing dot and status text ("building", "verifying") but not descriptive activity text.

**Status:** This would require the agent to report real-time activity status, which is not part of the current agent protocol. Accept as a future enhancement.

### G-10: No "Tail Logs" section in inspector (P1, frontend)

**Spec says** (Section 3.4): Inspector panel includes a "TAIL LOGS" section with recent log output preview.

**Actual:** The InspectorPanel has: Selected Task card, Attempt History, Requirements & Grades, and a Debug button. No log preview.

**Impact:** Users can't see agent output without leaving the UI.

**Fix:** Add a tail logs section. Could source from WebSocket events or a dedicated log endpoint. Partially blocked by backend — no log streaming endpoint currently exists.

### G-11: Inspector missing attempt summary text (P2, frontend)

**Spec says** (Section 3.4): Each attempt in the inspector shows a summary description (e.g., "Self-correction triggered: Missing context for JWT...", "Generating markdown structure based on updated prompts.").

**Actual:** Attempts show attempt number, outcome, duration, and token counts. No narrative summary text.

**Impact:** Minor — the backend doesn't generate attempt summaries. Would need agent output integration.

### G-12: No source path in routine library section headers (P2, frontend)

**Spec says** (Section 4.1): Source section headers show the directory path (e.g., `~/user/routines`, `./.orchestrator/...`).

**Actual:** Section headers show "Local Routines (3)" but not the filesystem path.

**Fix:** Backend would need to include the source directory path in the routine list response.

### G-13: Search bar not functional (P2, frontend) — RESOLVED

**Spec says** (Section 2.1): Header search bar searches "runs, routines, or logs" with `Cmd+K` shortcut.

**Fix applied:** `Cmd+K` now focuses the search input via `useRef` + global `keydown` listener in `Layout.tsx`. Pressing Enter navigates to `/?search=...` which the Dashboard reads via `useSearchParams` and applies as a text filter on runs (matches id, project_id, routine_id, status).

### G-14: Notification bell not functional (P2, frontend)

**Spec says** (Section 2.1): Notification bell in header.

**Actual:** Bell icon exists (`Layout.tsx:34-37`) but has no click handler or notification system.

**Status:** Placeholder — backend has no notification system yet.

### G-15: Sidebar not integrated with main layout (P1, frontend) — RESOLVED

**Spec says** (Section 4.1, 4.2): Routine Library uses a sidebar layout with navigation.

**Fix applied:** `Layout.tsx` now imports and renders `Sidebar` and `MobileBottomNav` as part of a unified flex layout (sidebar left, content right). All pages (Dashboard, Run Detail, Routine Library, Agents, History) share the same sidebar + header layout. `SidebarLayout.tsx` deleted as redundant.

### G-16: Agents and History pages don't exist (P2, frontend) — RESOLVED

**Spec says** (Section 4.2): Sidebar navigation includes "Agents" and "History" pages.

**Fix applied:** Added placeholder pages (`pages/Agents.tsx`, `pages/History.tsx`) with "Coming soon" messaging. Routes added in `App.tsx` under the unified layout. Sidebar navigation links now resolve correctly.

### G-17: "New Run" button in header links to dashboard instead of opening modal (P2, frontend) — RESOLVED

**Spec says**: "+ New Run" button opens the create run modal.

**Fix applied:** Created `CreateRunContext` (`context/CreateRunContext.tsx`) with `isOpen/open/close` state. `App.tsx` wraps routes in `<CreateRunProvider>`. Header button in `Layout.tsx` changed from `<Link>` to `<button onClick={openCreateRun}>`. Dashboard's local `showCreate` state replaced with `useCreateRunModal()` context hook.

---

## 3. Intentional Divergences from Spec

These differences were deliberate decisions based on data model alignment.

### D-01: Inspector uses priority-grouped checklist instead of SYNTAX/LOGIC/SECURITY/PERF grid

**Spec says** (Section 3.4): Inspector shows a 2x2 grid with rubric categories: SYNTAX, LOGIC, SECURITY, PERF.

**Implementation:** Shows checklist items grouped by priority tier (Required, Expected, Optional) with per-item grade badges.

**Rationale:** The spec's fixed SYNTAX/LOGIC/SECURITY/PERF categories don't exist in the data model. Checklist items are defined per-task in routines with flexible descriptions and priority levels. The current implementation accurately reflects the actual data structure. The spec should be updated.

### D-02: Routine cards show source badge instead of version badge

**Spec says**: Cards show "v1.2" version badge.

**Implementation:** Cards show a source badge (Local/Project/External) since version data isn't available (Phase 7 feature).

**Rationale:** Source type is available and useful information. Version will be added when Phase 7 (git integration) is implemented.

### D-03: Dashboard collapsed row includes routine_id in meta

**Spec says**: Meta line shows "ID: #8390-B | Routine: Doc-Updater | Project: Core-API".

**Implementation:** Shows shortened UUID | routine_id | project_id.

**Rationale:** The system uses UUIDs for run IDs rather than short human-readable IDs. The displayed data is functionally equivalent but less compact.

---

## 4. Visual/Polish Gaps

Minor cosmetic differences from the spec.

### V-01: No slide-down animation on run card expansion (P2, frontend) — RESOLVED

**Spec says** (Section 7.1): "Expansion is animated (slide down)".

**Fix applied:** Expanded content (step columns + footer) in `RunCard.tsx` wrapped in `<div className="animate-slide-down overflow-hidden">`. Uses the `slide-down` keyframe animation already defined in `index.css`.

### V-02: No green glow on active runs (P2, frontend) — RESOLVED

**Spec says** (Section 7.3): "Active runs pulse with subtle green glow".

**Fix applied:** `RunCard` wrapper div now includes `animate-pulse-glow` class when `run.status === 'active'`. Uses the `pulse-glow` keyframe animation already defined in `index.css` (8-16px green box-shadow pulse).

### V-03: Grade badge hover tooltip not implemented (P2, frontend) — RESOLVED (already working)

**Spec says** (Section 7.4): "Hover on grade badge → Show tooltip with full rubric text".

**Status:** Already working. `GradeBadge` component uses native `title={tooltip}` attribute, which renders a browser tooltip on hover. The `tooltip` prop is passed as `item.grade_reason` from `InspectorPanel.tsx`.

### V-04: No "Create Local Routine" placeholder visible without routines (P2, frontend)

The placeholder "Create Local Routine" card exists in RoutineLibrary but only shows when there are existing local routines in the list. When the library is empty, the empty state hides the placeholder.

### V-05: Agent Guidance Panel exists but not in spec (P2, frontend)

**Not in spec:** The `AgentGuidancePanel` component (shown for `user_managed` agent type) exists in the implementation but isn't documented in `22-UI-SPECIFICATION.md`. However, it's described in Section 6 of the spec as a general pattern.

**Status:** This is a useful addition. The spec should be updated to reference it.

---

## 5. Summary Priority Matrix

| ID | Severity | Type | Description |
|----|----------|------|-------------|
| G-01 | ~~P0~~ | ~~backend~~ | ~~Step progression not tracked~~ — **RESOLVED** |
| G-02 | ~~P0~~ | ~~backend~~ | ~~Run status doesn't auto-transition to COMPLETED~~ — **RESOLVED** |
| G-03 | ~~P1~~ | ~~both~~ | ~~Task title not in summary response~~ — **RESOLVED** (was already working) |
| G-04 | ~~P1~~ | ~~backend~~ | ~~No per-attempt grade snapshots~~ — **RESOLVED** |
| G-07 | ~~P1~~ | ~~frontend~~ | ~~No grade badges in task cards~~ — **RESOLVED** |
| G-08 | ~~P1~~ | ~~frontend~~ | ~~No retry stacking in task cards~~ — **RESOLVED** |
| G-10 | P1 | frontend | No tail logs section in inspector (needs backend log streaming) |
| G-15 | ~~P1~~ | ~~frontend~~ | ~~Sidebar not integrated into layout~~ — **RESOLVED** |
| G-05 | P1 | backend | No version/git SHA on routines (Phase 7 dependency) |
| G-09 | P2 | frontend | No descriptive activity status on active tasks (needs agent protocol) |
| G-11 | P2 | frontend | No attempt summary text in inspector (needs agent output) |
| G-12 | P2 | both | No source path in routine section headers (needs backend) |
| G-13 | ~~P2~~ | ~~frontend~~ | ~~Search bar non-functional~~ — **RESOLVED** |
| G-14 | P2 | frontend | Notification bell non-functional (needs backend notification system) |
| G-16 | ~~P2~~ | ~~frontend~~ | ~~Agents and History pages don't exist~~ — **RESOLVED** (placeholder pages) |
| G-17 | ~~P2~~ | ~~frontend~~ | ~~Header "New Run" button links instead of opening modal~~ — **RESOLVED** |
| V-01 | ~~P2~~ | ~~frontend~~ | ~~No expand/collapse animation~~ — **RESOLVED** |
| V-02 | ~~P2~~ | ~~frontend~~ | ~~No green glow on active runs~~ — **RESOLVED** |
| V-03 | ~~P2~~ | ~~frontend~~ | ~~Grade badge hover tooltip~~ — **RESOLVED** (was already working) |
| G-06 | P2 | frontend | Cost estimation is client-side approximation (acceptable) |

---

## 6. Recommended Next Steps

1. ~~**Backend P0 fixes (G-01, G-02):**~~ **RESOLVED.**
2. ~~**Backend P1 fix (G-03):**~~ **RESOLVED** (was already working).
3. ~~**Frontend P1 fixes (G-07, G-08, G-15):**~~ **RESOLVED.** Grade badges in task cards, retry stacking, sidebar integrated into unified layout.
4. **Spec updates (D-01, D-02, V-05):** Update `22-UI-SPECIFICATION.md` to reflect intentional divergences.
5. **Phase 7 dependencies (G-05):** Routine versioning will resolve version badges once git integration is implemented.
6. **Remaining deferred items:** G-10 (log streaming), G-09/G-11 (agent output), G-12 (source paths), G-14 (notifications) — all require backend work or agent protocol changes.

---

## 7. Root Cause Analysis: G-01 and G-02

This section traces whether step progression tracking (G-01) and run auto-completion (G-02) were specified in the slice documents but missed during implementation, or whether they were never specified at all.

### 7.1 Summary Verdict

**Both G-01 and G-02 are planning failures.** The slice documents for Phases 1-5 never specify the logic for advancing `current_step_index`, marking steps as completed, or auto-transitioning run status to COMPLETED when all tasks finish. The implementation faithfully follows the slices as written -- the slices simply did not include these behaviors.

### 7.2 Detailed Evidence

#### 7.2.1 What the data model provides (Slice 1.4: State Models)

The Phase 1 slice document (`docs/intent/11-SLICES-PHASE-1.md`, Slice 1.4) defines the state models with the necessary fields:

- `StepState.completed: bool = False` (line ~841 of slice doc; `/src/orchestrator/state/models.py:81`)
- `Run.current_step_index: int = 0` (line ~869 of slice doc; `/src/orchestrator/state/models.py:110`)

Both fields exist in the implementation exactly as specified. However, the slice only defines the **data structures** -- it never specifies any logic or transition rules that would modify these fields.

#### 7.2.2 What the task state machine covers (Slice 2.3: Task State Machine)

The Phase 2 slice document (`docs/intent/12-SLICES-PHASE-2.md`, Slice 2.3) defines the task-level state machine with these transitions:

```
PENDING -> BUILDING
BUILDING -> VERIFYING (if checklist gate passes)
VERIFYING -> COMPLETED (if grades pass)
VERIFYING -> BUILDING (revision if grades fail, attempts remain)
BUILDING -> FAILED (max attempts on checklist failure)
VERIFYING -> FAILED (max attempts on grade failure)
```

This is exclusively task-level. The slice defines `VALID_TRANSITIONS` as a `dict[TaskStatus, set[TaskStatus]]` and three pure functions: `transition_to_building`, `transition_to_verifying`, and `transition_after_verification`. The implementation in `/src/orchestrator/workflow/transitions.py` matches this specification exactly.

**Critically absent from Slice 2.3:**
- No `StepStatus` enum or step-level state machine
- No transition function for step completion
- No transition function for run completion
- No mention of checking whether sibling tasks in a step are all done
- No mention of advancing `current_step_index`

#### 7.2.3 What the workflow engine covers (Slice 2.4: Workflow Engine)

The Phase 2 slice document (`docs/intent/12-SLICES-PHASE-2.md`, Slice 2.4) defines the `WorkflowEngine` class with these methods:

- `start_run()` -- DRAFT/QUEUED to ACTIVE
- `start_task()` -- delegates to `transition_to_building`
- `submit_for_verification()` -- delegates to `transition_to_verifying`
- `complete_verification()` -- delegates to `transition_after_verification`

The integration test scenario in the slice (lines ~574-582) describes a single-task lifecycle:

```
1. Create run from routine
2. Start run
3. Start task (PENDING -> BUILDING)
4. Update checklist items to DONE
5. Submit for verification (BUILDING -> VERIFYING)
6. Set grade on each individual requirement
7. Complete verification (VERIFYING -> COMPLETED)
8. Verify final state
```

**Critically absent from Slice 2.4:**
- No `complete_run()` method or equivalent
- No post-task-completion hook that checks step/run state
- No logic in `complete_verification()` to cascade task completion upward to step or run
- The integration test only covers a single task in a single step -- multi-step progression is never tested
- The milestone verification script at the end of Phase 2 (lines ~777-823) also tests only a single task

The implementation in `/src/orchestrator/workflow/engine.py` faithfully reproduces this design. The `complete_verification()` method (lines 186-217) calls `transition_after_verification`, emits events, and updates the run state -- but performs no check on step or run completion.

#### 7.2.4 What the enums define (Slice 1.2: Configuration Models)

The Phase 1 slice (`docs/intent/11-SLICES-PHASE-1.md`, Slice 1.2) defines `RunStatus` with a `COMPLETED` value and `TaskStatus` with a `COMPLETED` value. However, there is **no `StepStatus` enum**. Steps use a simple `completed: bool` flag instead of a full status enum.

The implementation in `/src/orchestrator/config/enums.py` matches: `RunStatus` has COMPLETED, `TaskStatus` has COMPLETED, but no `StepStatus` exists.

#### 7.2.5 What the architecture document says

The architecture document (`docs/intent/01-ARCHITECTURE.md`, Section 4.1) shows the run lifecycle state machine:

```
DRAFT -> QUEUED -> ACTIVE <-> PAUSED -> COMPLETED/FAILED
```

The CLAUDE.md core flow states: "Pass: next task | Revision: back to Builder". This implicitly acknowledges that there should be progression to the "next task," but this concept is never formalized into a step-advancement or run-completion mechanism in any slice document.

The implementation plan (`docs/intent/05-IMPLEMENTATION-PLAN.md`, Step 6.2) includes a `complete_run()` function that sets `run.status = RunStatus.COMPLETED`, but this is in Phase 6 (Completion Actions) which is about worktree cleanup, not about auto-detecting when all tasks are done. It assumes something else has already determined the run should be completed.

#### 7.2.6 What the WorkflowService adds (Phase 3/4)

The `WorkflowService` (`/src/orchestrator/workflow/service.py`) wraps the `WorkflowEngine` for async/persistence. Its `complete_verification()` method (lines 144-150) delegates directly to `engine.complete_verification()` and persists the result -- but adds no step or run completion logic of its own.

#### 7.2.7 The gap in the Phase 2 milestone verification

The Phase 2 milestone verification script (Slice 2.4, end of Phase 2) loads a `valid_simple.yaml` routine that has a single step with a single task. The script runs one task through completion and asserts `task.status == TaskStatus.COMPLETED`. It never tests:
- What happens when all tasks in a step complete
- What happens when all steps complete
- Whether `current_step_index` advances
- Whether `run.status` transitions to COMPLETED

This is the most telling evidence: the milestone verification was designed to succeed without step progression or run completion.

### 7.3 Why the gap exists

The slice documents were written with a bottom-up approach. Each phase builds on the previous:

1. **Phase 1** defines the data structures (including `current_step_index` and `step.completed`)
2. **Phase 2** defines the task-level state machine and workflow engine
3. **Phase 3** adds persistence
4. **Phase 4** adds API endpoints
5. **Phase 5** adds agent integration

The logical place for step-progression and run-completion logic would have been **Slice 2.4 (Workflow Engine)** -- specifically, `complete_verification()` should have included post-task-completion logic:

```
After task COMPLETED:
  1. Check if all tasks in the current step are COMPLETED
  2. If yes: mark step.completed = True, advance current_step_index
  3. Check if all steps are completed
  4. If yes: transition run to COMPLETED, set completed_at
```

This was never written into the slice. The fields `current_step_index` and `step.completed` were defined in Slice 1.4 as part of the data model, but no slice ever specified the logic to mutate them during workflow execution. They exist as "dead" fields -- defined but never written to by any workflow operation.

### 7.4 Step-level status tracking

The UI specification (`docs/intent/22-UI-SPECIFICATION.md`, as referenced in G-01) assumes steps have statuses like `pending`, `in_progress`, `completed`, `failed`, and `skipped`. However:

- **No `StepStatus` enum exists** in `config/enums.py` or anywhere in the codebase
- The `StepState` model has only a `completed: bool` field, not a `status` field
- The UI mockup (`docs/intent/07-UI-MOCKUP.html`, line ~132) references `step.status === 'completed'` and `step.status === 'in_progress'`, implying a richer step status model than what was built
- No slice document specifies adding a `StepStatus` enum or a `status` field to `StepState`

This is a disconnect between the UI design documents (which assumed step-level status tracking) and the backend slice documents (which never specified it).

### 7.5 Conclusion

| Gap | Classification | Root Cause | Status |
|-----|---------------|------------|--------|
| G-01: Step progression not tracked | **Planning failure** | Slice 1.4 defined `current_step_index` and `step.completed` fields but no slice specified the logic to advance them. Slice 2.4 (Workflow Engine) defined task-level operations only. No step-level state machine was ever designed. | **RESOLVED** — `check_step_progression()` added to `transitions.py`, called from `engine.py:complete_verification()`. |
| G-02: Run auto-completion missing | **Planning failure** | No slice specifies that completing the last task should trigger a run status transition to COMPLETED. The `complete_run()` concept appears only in the implementation plan's Phase 6 (completion actions) as a cleanup operation, not as an automatic state transition. | **RESOLVED** — `check_run_completion()` added to `transitions.py`, called from `engine.py:complete_verification()`. |
