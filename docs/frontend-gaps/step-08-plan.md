# Step 8 Plan: Validation + Env Files + Transitions + Dashboard WebSocket (Gaps 18, 19, 20, 21)

## Purpose

Add routine validation, env file management, non-linear step transition visualization, and real-time dashboard updates. This final step closes the remaining LOW-severity gaps and one gap (dashboard WebSocket) that may need backend coordination.

## Prerequisites

- None (independent of Steps 1–7, though all previous steps should ideally be complete for full integration testing)

## Functional Contract

### Inputs

- Routine validation: `yaml_content` (string) — raw YAML from a routine definition, submitted to `POST /api/routines/validate`
- Env file templates: `GET /api/runs/{id}/env-files` — returns list of env file templates with metadata (no values exposed in browser)
- Env file snapshots: `GET /api/runs/{id}/env-files/snapshots` — returns historical snapshots for revert
- Env file overrides: user-provided key-value overrides in CreateRunModal — merged with base template on run creation
- Step transitions: step progression data with `from_step` and `to_step` fields — includes backward jumps (e.g., step 5 → step 3)
- Dashboard WebSocket: aggregate channel broadcasting `run_status_changed` events for all runs visible on dashboard

### Outputs

- `pages/RoutineLibrary.tsx` updated: "Validate" button that submits YAML to validation endpoint and shows results inline (valid/invalid with error list)
- `useValidateRoutine()` mutation hook in `hooks/useApi.ts`
- `ValidateRoutineRequest` and `ValidateRoutineResponse` types in `types/routines.ts`
- `EnvFileTemplates` component at `components/EnvFileTemplates.tsx` — env file template list and management in config/settings area
- `EnvFileOverrides` component at `components/run/EnvFileOverrides.tsx` — per-run override inputs in CreateRunModal
- `useEnvFiles`, `useEnvFileSnapshots`, `useRevertEnvFile`, `useCopyBackEnvFile` hooks in `hooks/useApi.ts`
- Env file types in `types/envfiles.ts`
- `StepTimeline` updated: visual annotations (arrows, backward-jump indicators) for non-linear transitions
- `Dashboard` updated: WebSocket/SSE connection for aggregate run status updates, replacing 10s polling

### Errors

- Validation API returns errors → display error list inline below validate button with line numbers
- Validation API returns 500 → show "Validation service unavailable" error
- Env file API returns 404 → no env files configured → show "No env file templates" empty state
- Env file revert fails (snapshot not found) → show "Snapshot not found" error
- Dashboard WebSocket connection fails → fall back to existing 10s polling (graceful degradation)
- Dashboard WebSocket endpoint doesn't exist yet → show console warning, use polling fallback (may need backend work per Q4 design decision)

## Tasks

1. Create `types/routines.ts` with `ValidateRoutineRequest` and `ValidateRoutineResponse` types
2. Create `types/envfiles.ts` with `EnvFileSnapshot`, `RevertEnvFileRequest`, `CopyBackRequest` types
3. Add `useValidateRoutine`, `useEnvFiles`, `useEnvFileSnapshots`, `useRevertEnvFile`, `useCopyBackEnvFile` hooks to `hooks/useApi.ts`
4. Update `pages/RoutineLibrary.tsx` to add "Validate" button with inline results display
5. Create `components/EnvFileTemplates.tsx` for env file template management in config/settings area
6. Create `components/run/EnvFileOverrides.tsx` for per-run env overrides in CreateRunModal
7. Update `components/run/CreateRunModal.tsx` to include EnvFileOverrides section
8. Update `components/dashboard/StepTimeline.tsx` to visualize backward-jump transitions with arrows/annotations
9. Update `pages/Dashboard.tsx` to establish dashboard-level WebSocket/SSE connection with polling fallback

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `EnvFileTemplates.tsx` exists at `ui/src/components/EnvFileTemplates.tsx`
- [ ] `EnvFileOverrides.tsx` exists at `ui/src/components/run/EnvFileOverrides.tsx`
- [ ] `useValidateRoutine` is exported from `hooks/useApi.ts`
- [ ] `types/routines.ts` and `types/envfiles.ts` exist with type definitions

### Manual Verify

- [ ] Validate button on RoutineLibrary submits YAML and displays results
- [ ] Validation errors show with line numbers
- [ ] Env file templates can be viewed in config/settings area
- [ ] CreateRunModal shows env file override inputs when a template is selected
- [ ] StepTimeline correctly visualizes backward-jump transitions
- [ ] Dashboard receives real-time updates via WebSocket (or gracefully falls back to polling)

## Context & References

- Gap analysis: Gaps 18 (validation), 19 (env files), 20 (transitions), 21 (dashboard WS) — all LOW
- Design decision Q4: Dashboard aggregate WebSocket channel (may need backend work)
- Design decision Q5: Env files in config area with CreateRunModal overrides
- CONFLICTS.md: Dashboard WebSocket endpoint and env file template endpoint need backend verification
- Architecture: env file UI shows metadata only — values stay server-side (security)
- Performance: Dashboard WebSocket replaces polling — one connection per browser tab
