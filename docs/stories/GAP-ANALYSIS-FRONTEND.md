# Frontend Gap Analysis

Measured against the four user stories and the backbone journey map. Each section traces a story's narrative through the actual frontend code, noting where the UI supports the journey, where it's partial, and where it's missing.

---

## Story 01: The Happy Path

### What works

The core happy path is well-supported. The frontend has all the pieces:

| Story moment | Frontend support | Location |
|---|---|---|
| Browse routines | RoutineLibrary page with search and source filters | `pages/RoutineLibrary.tsx` |
| Inspect a routine | `GET /api/routines/{id}` called, detail shown | `hooks/useApi.ts → useRoutine()` |
| Check available agents | Agents page with available/unavailable sections | `pages/Agents.tsx` |
| Create a run | CreateRunModal with repo, branch, routine, agent selectors | `dashboard/CreateRunModal.tsx` |
| Start a run | Start button on RunCard, transitions DRAFT→ACTIVE | `dashboard/RunCard.tsx` |
| Watch activity stream | ActivityFeed with WebSocket push + SSE fallback | `detail/ActivityFeed.tsx` |
| See checklist updates | ChecklistTable renders status per requirement | `detail/ChecklistTable.tsx` |
| Trigger merge-back | Merge button on completed runs | `pages/RunDetail.tsx` |

### Gaps

| Gap | Severity | Detail |
|---|---|---|
| **No merge strategy selection** | Medium | Story describes `{ "strategy": "squash" }` as an explicit user choice. The frontend calls merge-back but doesn't expose a strategy picker -- it uses whatever the default is. The user can't choose between squash and merge. |
| **Routine inspection is shallow** | Low | Story shows Maya reading checklist items with priorities and gate config. The `RoutineDetail` type has `steps[]` but the UI displays them as simple lists -- no visual indication of gate types, auto-verify commands, or which items are CRITICAL vs NICE_TO_HAVE at the routine browsing stage. |
| **Agent selection happens at creation time only** | Low | The story implies Maya checks agents *then* creates. The UI bundles agent selection into CreateRunModal, which is fine, but the Agents page and CreateRunModal are disconnected -- selecting an agent on the Agents page doesn't carry that choice into run creation. |

---

## Story 02: The Revision Loop

### What works

| Story moment | Frontend support | Location |
|---|---|---|
| Auto-verify results shown | Activity events include auto-verify pass/fail | `detail/ActivityFeed.tsx` |
| Grade display per requirement | GradeBadge + grade_reason in ChecklistTable | `detail/ChecklistTable.tsx` |
| Attempt history | AttemptHistory shows per-attempt outcomes | `detail/AttemptHistory.tsx` |
| Token/cost tracking | MetricsBar shows totals | `detail/MetricsBar.tsx` |

### Gaps

| Gap | Severity | Detail |
|---|---|---|
| **No per-attempt cost breakdown** | Medium | Story ends with Maya seeing `tokens: 12400` / `15200` / `14800` per attempt. MetricsBar shows only run-level totals. AttemptHistory shows outcomes and grades but not token counts or cost per attempt. The data may be in `attempts_summary` but it's not rendered. |
| **Auto-verify output not surfaced** | Medium | Story shows the actual test failure (`AssertionError: expected 401, got 500`). The activity feed shows events but auto-verify command output (stdout/stderr) isn't displayed inline. Users see "auto-verify FAILED" but not *why* without digging into logs. |
| **No visual revision loop indicator** | Low | Story makes the attempt cycle (build→verify→revise→build) very clear. The UI shows attempt count (`2/3`) but doesn't visualize the loop itself -- there's no timeline or flow diagram showing "attempt 1: auto-verify failed → attempt 2: grade threshold failed → attempt 3: passed." AttemptHistory is close but presents it as a flat list, not a narrative. |
| **Grade threshold math not shown** | Low | Story explains "average is 3.5, threshold is 3.0, but R3 CRITICAL is below PASS." The frontend shows individual grades but doesn't show the threshold calculation or explain *why* a verification failed when individual grades look mostly fine. |

---

## Story 03: The Human in the Loop

### What works

| Story moment | Frontend support | Location |
|---|---|---|
| Clarification notification | PendingActionsBadge on dashboard, auto-modal on RunDetail | `dashboard/PendingActionsBadge.tsx`, `pages/RunDetail.tsx` |
| Answer clarification | ClarificationModal with options + free text | `detail/ClarificationModal.tsx` |
| Step approval gate | ApprovalModal with summary + approve/reject | `detail/ApprovalModal.tsx` |
| Rejection with comment | RejectTask mutation sends comment | `hooks/useApproval.ts` |

### Gaps

| Gap | Severity | Detail |
|---|---|---|
| **No step-level approval UI (only task-level)** | High | Story describes `POST .../steps/{id}/approve` -- a step gate that blocks all tasks in step 2 until the human signs off. The backend has this endpoint. But the frontend's ApprovalModal is wired to *task* approval (`useApproveTask`, `useRejectTask`). There's no UI for step-level gates. The `PendingAction` type includes `step_id` and `action_type` but the rendering logic in RunDetail routes everything through task-level modals. A step gate would show as a pending action but the approve button would call the wrong endpoint. |
| **Clarification context is thin** | Medium | Story shows the agent providing rich context ("JSON is simpler but harder to query. Normalized is more flexible but adds joins."). ClarificationModal renders `question` and `options[]` but the `context` field on `ClarificationQuestion` -- which could contain the agent's reasoning -- isn't displayed. |
| **No indication of *which* gate is blocking** | Medium | Story distinguishes between "step requires human approval" and "task needs review." The UI shows "Review needed" or "Answer needed" badges but doesn't communicate the gate type. A user seeing a blocked step 2 doesn't know if it's a human_approval gate, a grade_threshold gate, or a checklist gate without reading the routine definition. |
| **No "waiting for approval" state visualization** | Low | Story describes the run staying ACTIVE but the agent having nothing to do while waiting for step approval. The UI shows run status as ACTIVE (green) with no visual cue that progress is actually blocked on human input. The run looks healthy when it's actually stalled. |

---

## Story 04: The Long-Running Run

### What works

| Story moment | Frontend support | Location |
|---|---|---|
| Pause / resume | Buttons on RunCard and RunDetail | Both pages |
| Resume with different agent | ResumeDialog with agent/config override | `run/ResumeDialog.tsx` |
| Activity log pagination | `useActivity` with `after` cursor, `has_more` | `hooks/useApi.ts` |
| Run listing with filters | Dashboard filters: status, repo, recency, search | `dashboard/RunFilters.tsx` |
| WebSocket connection indicator | ConnectionIndicator shows connected/disconnected | `ConnectionIndicator.tsx` |

### Gaps

| Gap | Severity | Detail |
|---|---|---|
| **No branch status display** | High | Story revolves around `GET .../branch-status` showing 12 ahead / 4 behind. The backend endpoint exists. The frontend never calls it. There's no UI anywhere showing how the run branch relates to the source branch. Users can't see if upstream has diverged. |
| **No back-merge UI** | High | Story describes `POST .../back-merge` to pull upstream changes. No frontend button, dialog, or endpoint call for this. Users who need to back-merge must use the CLI or API directly. |
| **No merge strategy picker** | Medium | (Same as Story 01) Story shows Jordan explicitly choosing `--strategy merge` to preserve history. Frontend has no strategy selection. |
| **No "step X of Y" progress on dashboard** | Medium | Story shows `orchestrator runs list` returning `Step 3/5`. The dashboard RunCard shows a StepTimeline (mini progress bar) but the list view in the CLI-style "which step am I on" sense isn't as immediately readable. The progress bar is visual but doesn't communicate "3 of 5 complete" in text. |
| **History page is stubbed** | Medium | Story implies Jordan can look back at completed runs to understand past work. The History page is a "Coming soon" placeholder. Completed runs are visible on the Dashboard (filter by status=completed) but there's no dedicated history view with search, date ranges, or outcome summaries. |
| **No run duration tracking visible during execution** | Low | Story implies awareness of elapsed time ("20-30 minutes"). MetricsBar shows `total_duration_ms` but only for completed runs. During execution, there's no elapsed time display or progress estimation. |

---

## Cross-Cutting Gaps (Not Story-Specific)

These emerged from comparing the backbone's full capability list against the frontend inventory:

| Gap | Severity | Detail |
|---|---|---|
| **No guidance endpoint UI for user-managed agents** | Medium | The backbone lists `GET .../guidance` for external agents. There is an `AgentGuidancePanel` component, but it's a static instruction panel -- it doesn't poll or display the live guidance response. An external agent operator using the web UI gets setup instructions but can't see the current prompt or expected actions. |
| **No routine validation UI** | Low | Backbone lists `POST /api/routines/validate`. No frontend call. Users writing routines can't validate them from the UI. |
| **No env file management** | Low | Backend has env file endpoints (`api/routers/envfiles.py`). No frontend equivalent. Env files can only be managed via API/CLI. |
| **Conditional step transitions invisible** | Low | Backend supports `on_condition` transitions (e.g., jump back to step 1 if checklist incomplete). The frontend step progress bar doesn't visualize non-linear flow -- it assumes steps go left to right. A backward jump would update the step states but the UI wouldn't explain *why* step 3 suddenly went back to pending. |
| **No SSE activity stream on dashboard** | Low | SSE/WebSocket streaming is only wired up on RunDetail. The Dashboard polls every 10s. For users monitoring multiple runs, updates are delayed. |

---

## Summary by Severity

### High (blocks a story journey)

1. **No step-level approval UI** -- Story 03's central gate mechanism doesn't work in the frontend
2. **No branch status display** -- Story 04's awareness of divergence has no UI
3. **No back-merge UI** -- Story 04's key operation isn't accessible from the frontend

### Medium (degrades a story journey)

4. No merge strategy selection (Stories 01, 04)
5. No per-attempt cost breakdown (Story 02)
6. Auto-verify output not surfaced (Story 02)
7. Clarification context field not displayed (Story 03)
8. No gate type indication (Story 03)
9. Step progress not textual on dashboard (Story 04)
10. History page stubbed (Story 04)
11. Guidance endpoint not live-rendered (Backbone)

### Low (minor friction or missing polish)

12. Routine inspection doesn't show gate types or priorities
13. Agents page disconnected from run creation flow
14. No visual revision loop indicator
15. Grade threshold calculation not explained
16. No "blocked on human" visual state
17. No elapsed time during execution
18. No routine validation from UI
19. No env file management in UI
20. Conditional step transitions not visualized
21. No real-time updates on dashboard (polling only)

---

## Recommended Priorities

The three **high** items form a natural first pass -- they represent backend capabilities that exist but have no frontend surface at all. Fixing them is straightforward (the API contracts already exist) and would make the story journeys fully executable through the web UI.

The **medium** items cluster around two themes: *transparency* (showing the user what happened and why -- auto-verify output, grade math, gate types) and *git awareness* (merge strategy, branch status). These are the difference between a UI that lets you drive the system and one that helps you understand it.
