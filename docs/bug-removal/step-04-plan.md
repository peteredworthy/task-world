# Step 4 Plan: Add Recovery UI (FAILED-RUN-RECOVERY — Frontend)

## Purpose

Surface the run recovery API to the user by adding a `RecoveryPanel` to the `RunDetail` page. When a run is in `FAILED` status, the user will see a step/task timeline with clickable rollback points and a confirmation dialog. Currently there is no UI for recovery; users must call the API directly or manipulate the database. This step makes failed-run recovery accessible to non-technical users.

## Prerequisites

- Step 3 (failed-run recovery API) must be complete and deployed — `POST /api/runs/{id}/recover` must exist and return `RecoverResponse`

## Functional Contract

### Inputs

- Run detail data from `GET /api/runs/{id}` — `status === "FAILED"` signals the recovery panel should render
- Step and task timeline data from the same run detail response — used to render clickable rollback points
- User-selected `target_task_id` — the task to roll back to (from clicking a step/task in the timeline)
- Optional: `preserve_checklist` boolean toggle in the confirmation dialog

### Outputs

- `recoverRun(runId, data: RecoverRequest)` function added to `ui/src/api/client.ts`
- `useRecoverRun()` mutation hook added to `ui/src/hooks/useApi.ts`; invalidates `['run', runId]` on success
- `RecoverRequest` and `RecoverResponse` types added to `ui/src/types/`
- `RecoveryPanel` component (new file at `ui/src/components/detail/RecoveryPanel.tsx` or inline in `RunDetail.tsx`):
  - Renders only when `run.status === "FAILED"`
  - Displays step/task timeline with each task showing its last status and `end_commit`
  - Clicking a task sets it as the rollback target and opens a confirmation dialog
  - Confirmation dialog shows what will be reset and has a `preserve_checklist` toggle
  - On confirm, calls `useRecoverRun`; on success, displays success message and invalidates run query
- `RunDetail.tsx` mounts `RecoveryPanel` for FAILED runs

### Errors

- 404 from recover API — show error toast "Task not found for this run"
- 409 from recover API — show error toast "Run must be in FAILED status to recover"
- Network error — show generic retry toast; keep dialog open
- TypeScript compile errors must be zero after all changes

## Tasks

1. Add `RecoverRequest` and `RecoverResponse` types to `ui/src/types/` (fields: `target_task_id`, `additional_attempts?`, `agent_type?`, `agent_config?`, `preserve_checklist?`)
2. Add `recoverRun(runId, data)` to `ui/src/api/client.ts` calling `POST /api/runs/{runId}/recover`
3. Add `useRecoverRun()` mutation hook to `ui/src/hooks/useApi.ts` with run query invalidation on success
4. Create `ui/src/components/detail/RecoveryPanel.tsx` with step/task timeline, rollback target selection, and confirmation dialog
5. Update `ui/src/pages/RunDetail.tsx` to mount `RecoveryPanel` when `run.status === "FAILED"`
6. Write Vitest test: render `RecoveryPanel` with a mock FAILED run; confirm timeline renders and confirmation dialog appears on task click

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `RecoveryPanel.tsx` exists at `ui/src/components/detail/RecoveryPanel.tsx`
- [ ] `recoverRun` is exported from `ui/src/api/client.ts`
- [ ] `useRecoverRun` is exported from `ui/src/hooks/useApi.ts`
- [ ] Vitest test for `RecoveryPanel` passes

### Manual Verify

- [ ] `RunDetail` page for a FAILED run shows the `RecoveryPanel` with step/task timeline
- [ ] Clicking a task in the timeline opens a confirmation dialog showing what will be reset
- [ ] Confirming recovery calls the correct API endpoint and transitions the run to PAUSED in the UI
- [ ] Panel is hidden for non-FAILED runs (ACTIVE, PAUSED, COMPLETED)

## Context & References

- Bug report: `docs/bugs/FAILED-RUN-RECOVERY.md` — UI section
- Architecture: `docs/bug-removal/architecture.md` — "New Components: RecoveryPanel", "Modified Components: RunDetail.tsx"
- Clarification: recovery is FAILED-only; no COMPLETED run support in this step
- Clarification: `preserve_checklist` defaults to `false`; dialog should expose a toggle
- Prerequisite: Step 3 (recovery backend API)
