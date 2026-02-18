# Feature: Env File Management UI

## Summary

The backend has a full set of env file endpoints (list, snapshots, revert, copy-back,
default-target) with integration tests, but the frontend has no UI to view or manage env
file snapshots during a run. Users must resort to the CLI or direct API calls.

## Current State

**Backend — complete:**
- `GET /api/runs/{id}/env-files` — current env file contents (masked values)
- `GET /api/runs/{id}/env-files/snapshots` — snapshot history with task boundaries
- `POST /api/runs/{id}/env-files/revert` — revert to a specific snapshot
- `POST /api/runs/{id}/env-files/copy-back` — write snapshot back to project directory
- `GET /api/runs/{id}/env-files/default-target` — default copy-back target path
- Tests: `tests/integration/test_api_runs_envfiles.py`

**Frontend — nothing:**
- No API client functions for any of the five endpoints
- No types for `EnvFile`, `EnvSnapshot`, `EnvDefaultTarget`
- No query/mutation hooks
- No UI component

## Work Required

1. **`ui/src/types/`** — add `EnvFile`, `EnvSnapshot`, `EnvDefaultTarget` types.

2. **`ui/src/api/client.ts`** — add functions for all five endpoints:
   `getEnvFiles`, `getEnvSnapshots`, `getEnvDefaultTarget`, `revertEnvSnapshot`,
   `copyBackEnvFiles`.

3. **`ui/src/hooks/useApi.ts`** — add `useEnvFiles`, `useEnvSnapshots`,
   `useEnvDefaultTarget` queries; `useRevertEnvSnapshot`, `useCopyBackEnvFiles` mutations.

4. **New component `EnvFilesPanel`** in `ui/src/components/detail/`:
   - List current env files with masked values
   - Snapshot history table (timestamp, task boundary label)
   - "Revert to this snapshot" button per row (calls `useRevertEnvSnapshot`)
   - "Copy back to project" button with target path display (calls `useCopyBackEnvFiles`)

5. **`ui/src/pages/RunDetail.tsx`** — add `EnvFilesPanel` as a collapsible section or tab,
   shown only when `run.env_file_specs` is non-empty.

## Severity

**Low-Medium** — env file management works via CLI; the UI gap affects usability for
non-CLI workflows.

## Related

- `docs/ui-gaps2/README.md §7`
- `src/orchestrator/api/routers/envfiles.py` — all five endpoints
- `tests/integration/test_api_runs_envfiles.py`
- `ui/src/types/runs.ts` — `RunResponse.env_file_specs` (already present)
