# Step 10 Plan: Env File Management UI (UI-ENV-FILE-MANAGEMENT)

## Purpose

Add an `EnvFilesPanel` to `RunDetail` that lists the run's current env files (with masked values), shows snapshot history, and provides revert and copy-back actions. The backend env file endpoints already exist and are tested; this step adds five client functions, five hooks, new types, and the `EnvFilesPanel` component. The panel is only shown when `run.env_file_specs` is non-empty.

## Prerequisites

- None (independent of all other steps)

## Functional Contract

### Inputs

- `run_id` (string) from the `RunDetail` route params
- `run.env_file_specs` array — if empty, the panel is not rendered
- Env file API responses: current files list (masked values), snapshot history list, default target path
- User-selected snapshot for revert or copy-back actions, with confirmation

### Outputs

- Five client functions added to `ui/src/api/client.ts`:
  - `getEnvFiles(runId)` → list of current env files with masked values
  - `getEnvSnapshots(runId)` → snapshot history
  - `getEnvDefaultTarget(runId)` → default target path for copy-back
  - `revertEnvSnapshot(runId, snapshotId)` → revert worktree env files to a snapshot
  - `copyBackEnvFiles(runId, targetPath)` → write env files from worktree back to source path
- Five hooks added to `ui/src/hooks/useApi.ts`:
  - `useEnvFiles(runId)` — query
  - `useEnvSnapshots(runId)` — query
  - `useEnvDefaultTarget(runId)` — query
  - `useRevertEnvSnapshot()` — mutation, invalidates env queries on success
  - `useCopyBackEnvFiles()` — mutation, shows confirmation before executing
- New types added to `ui/src/types/`: `EnvFile`, `EnvSnapshot`, `EnvDefaultTarget`
- `EnvFilesPanel` component (new file at `ui/src/components/detail/EnvFilesPanel.tsx`):
  - Current files section: lists file names and masked values
  - Snapshot history table: shows snapshot timestamp, agent, and action buttons (Revert, Copy Back)
  - Revert action requires confirmation dialog before calling `useRevertEnvSnapshot`
  - Copy Back action requires path confirmation before calling `useCopyBackEnvFiles`
- `RunDetail.tsx` mounts `EnvFilesPanel` when `run.env_file_specs` is non-empty

### Errors

- Any env file API 404 — panel shows "No env files configured" placeholder
- Revert API error — show error toast; keep panel visible for retry
- Copy-back API error — show error toast with the server's error message
- TypeScript compile errors must be zero

## Tasks

1. Add `EnvFile`, `EnvSnapshot`, `EnvDefaultTarget` types to `ui/src/types/`
2. Add `getEnvFiles`, `getEnvSnapshots`, `getEnvDefaultTarget`, `revertEnvSnapshot`, `copyBackEnvFiles` to `ui/src/api/client.ts`
3. Add `useEnvFiles`, `useEnvSnapshots`, `useEnvDefaultTarget`, `useRevertEnvSnapshot`, `useCopyBackEnvFiles` to `ui/src/hooks/useApi.ts`
4. Create `ui/src/components/detail/EnvFilesPanel.tsx` with current files list, snapshot history, and action buttons with confirmation dialogs
5. Update `ui/src/pages/RunDetail.tsx` to mount `EnvFilesPanel` when `run.env_file_specs` is non-empty
6. Write Vitest test: render `EnvFilesPanel` with mock snapshot data; confirm snapshot table renders and revert button is present

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `EnvFilesPanel.tsx` exists at `ui/src/components/detail/EnvFilesPanel.tsx`
- [ ] All five client functions are exported from `ui/src/api/client.ts`
- [ ] All five hooks are exported from `ui/src/hooks/useApi.ts`
- [ ] `EnvFile`, `EnvSnapshot`, `EnvDefaultTarget` types are defined and exported
- [ ] Vitest test for `EnvFilesPanel` passes

### Manual Verify

- [ ] `EnvFilesPanel` appears on `RunDetail` for runs with non-empty `env_file_specs`
- [ ] Panel is hidden for runs with empty or null `env_file_specs`
- [ ] Current files list shows masked values (not plaintext secrets)
- [ ] Snapshot history table shows all snapshots with timestamps
- [ ] Revert action prompts for confirmation before calling the API
- [ ] Copy-back action prompts for target path confirmation before calling the API

## Context & References

- Bug report: `docs/bugs/UI-ENV-FILE-MANAGEMENT.md`
- Architecture: `docs/bug-removal/architecture.md` — "New Components: EnvFilesPanel", "Modified Components: RunDetail.tsx"
- Backend: existing env file endpoints in `src/orchestrator/api/routers/runs.py`; integration tests at `tests/integration/test_api_runs_envfiles.py`
- Security note: masked values are a backend guarantee; the frontend must not attempt to unmask or log raw values
