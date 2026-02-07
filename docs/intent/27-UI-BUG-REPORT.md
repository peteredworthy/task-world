# UI & Backend Bug Report

Generated 2026-02-06 from systematic testing of the full stack. Last updated 2026-02-06.

## Legend

- **Fix Complexity**: `trivial` (< 10 lines, obvious), `simple` (< 50 lines, clear approach), `design-needed` (requires decisions)

---

## Remaining Items

These features have backend support but are not yet exposed in the UI.

### F1. Human Approval Gates (UI + CLI) [MEDIUM]

- **Status**: Backend fully implemented (models, gate logic, API endpoint, DB persistence, tests). See Phase 9, Slice 9.1 in `docs/intent/19-SLICES-PHASE-9.md`.
- **What's missing**:
  - UI: No approval prompt display, no approve button, no indication a step needs approval
  - CLI: No `orchestrator run approve` command (documented in slice but not built)
  - MCP: No approval tools
  - Workflow: After approval is recorded, gate re-evaluation and step advancement are not automated
- **Scope**: Feature completion task

### F2. Agent Logs Viewer [MEDIUM]

- **Backend**: `GET .../attempts/{num}/logs` exists and returns agent output
- **UI**: No component to display logs
- **Decision**: Add to the detailed view of a run, within the task panel
- **Scope**: New UI component needed

### F3. Backward Step Transitions [LOW]

- **Backend**: `POST /transition-back` exists
- **UI**: No trigger
- **Scope**: Needs UX design for when/how to show this option

### F4. Git Branch Operations [LOW]

- **Backend**: Branch status, merge-back, back-merge endpoints exist
- **UI**: None exposed
- **Scope**: Phase 7 features, may be intentionally deferred

### F5. Environment File Management [LOW]

- **Backend**: Full CRUD endpoints exist for env files
- **UI**: Not exposed at all
- **Scope**: Needs UX design

---

## Completed (Fixed)

All bugs and features below have been resolved. Kept for reference.

### B1. No run status guard on task operations [FIXED]

- **Files**: `src/orchestrator/workflow/service.py`
- **Fix applied**: All task operations (`start_task`, `submit_for_verification`, `complete_verification`, `update_checklist_item`, `set_grade`) now check `run.status == RunStatus.ACTIVE` and raise `InvalidTransitionError` if not.

### B2. Verification passes without any grades set [FIXED]

- **Files**: `src/orchestrator/workflow/grades.py:61-67`
- **Fix applied**: `evaluate_grades()` now returns `passed=False` with `message="no grades set"` when `graded_count == 0`.

### B3. Tasks in future steps can be started [FIXED]

- **Files**: `src/orchestrator/workflow/engine.py:214-229`
- **Fix applied**: `start_task()` now finds the task's step index and rejects if `step_index > run.current_step_index`.

### B4. Active runs can be deleted [FIXED]

- **Files**: `src/orchestrator/api/routers/runs.py:385-390`
- **Fix applied**: DELETE endpoint rejects with 409 if `run.status in (ACTIVE, PAUSED)`.

### B5. Grades can be set during building phase [FIXED]

- **Files**: `src/orchestrator/workflow/service.py:655-658`
- **Fix applied**: `set_grade()` checks `task.status == TaskStatus.VERIFYING` and raises `InvalidTransitionError` otherwise.

### B6. "Abort Run" button actually pauses [FIXED]

- **Files**: `ui/src/components/dashboard/RunCard.tsx:473`
- **Fix applied**: "Abort Run" button now calls `onCancel` which invokes `POST /cancel` endpoint, transitioning run to FAILED.

### B7. WebSocket batch messages silently ignored [FIXED]

- **Files**: `ui/src/hooks/useWebSocket.ts:49-55`
- **Fix applied**: Frontend now unwraps batch messages (`data.type === 'batch'`) and processes each event.

### B8. MetricsBar ignores backend cost estimate [FIXED]

- **Files**: `ui/src/components/detail/MetricsBar.tsx:45-50`
- **Fix applied**: Uses `run.estimated_cost_usd` from backend with fallback to client-side calculation.

### B9. No error feedback for pause/resume on RunDetail [FIXED]

- **Files**: `ui/src/pages/RunDetail.tsx:207`
- **Fix applied**: `pauseRun.mutate()` has `onError: handleMutationError('pause')` callback.

### B10. Search bar placeholder is misleading [FIXED]

- **Files**: `ui/src/components/Layout.tsx:49`
- **Fix applied**: Placeholder now says "Search runs..." instead of overpromising routines/logs.

### B13. 404 page missing Layout wrapper [FIXED]

- **Files**: `ui/src/App.tsx:24`
- **Fix applied**: NotFound route is now inside the Layout Route element.

### B14. No direct link from run card to run detail [FIXED]

- **Files**: `ui/src/components/dashboard/RunCard.tsx:465-470`
- **Fix applied**: Shows "Open Detailed View" link in footer.

### B15. Checklist items modifiable on completed tasks [FIXED]

- **Files**: `src/orchestrator/workflow/service.py:622-627`
- **Fix applied**: `update_checklist_item` and `set_grade` reject if `task.status in (COMPLETED, FAILED)`.

### B16. No grade value validation [FIXED]

- **Files**: `src/orchestrator/workflow/service.py:661-669`
- **Fix applied**: Validates grade against routine's configured `grade_scale` list.

### B17-B18. Non-functional "New Template" / "Create Local Routine" buttons [FIXED]

- **Files**: `ui/src/pages/RoutineLibrary.tsx`
- **Fix applied**: Buttons removed.

### B19. Type mismatch: `auto_verify_results` [FIXED]

- **Files**: `ui/src/types/tasks.ts:30`
- **Fix applied**: Type is now `Record<string, unknown>[] | null`.

### B20. Missing frontend types for backend fields [FIXED]

- **Files**: `ui/src/types/runs.ts`
- **Fix applied**: `source_branch`, `merge_strategy`, `env_file_specs` and other fields added to TypeScript interfaces.

### B21. Dead code path in `eventLabel` [FIXED]

- **Files**: `ui/src/components/detail/ActivityFeed.tsx:24-33`
- **Fix applied**: Logic restructured to avoid unreachable code.

### B22. Settings/Notifications buttons non-functional [FIXED]

- **Fix applied**: Notifications button removed. Settings button opens SettingsModal with SSE/polling toggle.

### B23. Agents page stub [FIXED]

- **Files**: `ui/src/pages/Agents.tsx`
- **Fix applied**: Displays full agent list from `GET /api/agents` with title, description, availability status, and config schema.

### F6. SSE Activity Streaming [FIXED]

- **Files**: `ui/src/components/SettingsModal.tsx`
- **Fix applied**: Settings modal has SSE/polling toggle. SSE is the default with polling fallback.

### F7. Cancel Run [FIXED]

- **Fix applied**: "Abort Run" button calls `POST /cancel` which transitions run to FAILED.

### F8. Queue Run [FIXED]

- **Fix applied**: `/queue` endpoint and `QUEUED` status removed. Runs go directly from DRAFT to ACTIVE via `start_run`.

### DB Migration Issue [FIXED]

- **Fix applied**: Alembic migrations implemented in `src/orchestrator/db/migrations/`. Initial schema migration exists.

### Polling Performance Concern [FIXED]

- **Files**: `ui/src/hooks/useApi.ts`
- **Fix applied**: Default polling interval changed from 2 seconds to 10 seconds. SSE now available as primary method.

---

## Notes

All items from the original bug report have been addressed. The remaining work (F1-F5) consists of feature completions for backend capabilities that aren't yet exposed in the UI.
