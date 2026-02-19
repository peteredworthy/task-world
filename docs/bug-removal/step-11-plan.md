# Step 11 Plan: Surface Server GlobalConfig in Settings Panel (UI-GLOBAL-CONFIG)

## Purpose

Display the server's runtime configuration (database path, active agent types, dashboard limits) in the UI settings panel so users can understand how their instance is configured. The backend `GET /api/config` endpoint exists but the frontend has no client function, type, hook, or UI for it. The run list currently uses a hardcoded constant for `max_recent_runs`; after this step it will use the server-provided value.

## Prerequisites

- None (independent of all other steps)

## Functional Contract

### Inputs

- `GET /api/config` response (`GlobalConfig`): includes `db_path`, `active_agent_types`, `max_recent_runs`, and other server-level settings
- Settings panel render context — the Server section is always shown; it does not depend on run state

### Outputs

- `getConfig()` function added to `ui/src/api/client.ts` calling `GET /api/config`
- `GlobalConfig` type added to `ui/src/types/`
- `useGlobalConfig()` query hook added to `ui/src/hooks/useApi.ts` with long `staleTime` (config rarely changes; use `staleTime: Infinity` or 5 minutes)
- Settings panel updated to include a "Server" section showing:
  - DB path
  - Active agent types list
  - Dashboard limits (`max_recent_runs`)
- Run list updated to use `useGlobalConfig().data.max_recent_runs` instead of any hardcoded constant

### Errors

- `getConfig` API 500 or network error — settings panel "Server" section shows "Unable to load server configuration" with a retry button
- TypeScript compile errors must be zero

## Tasks

1. Add `GlobalConfig` type to `ui/src/types/` matching the backend schema
2. Add `getConfig()` to `ui/src/api/client.ts`
3. Add `useGlobalConfig()` query hook to `ui/src/hooks/useApi.ts` with long `staleTime`
4. Update the settings panel component to include a "Server" section using `useGlobalConfig`
5. Update the run list component to use `useGlobalConfig().data.max_recent_runs` instead of a hardcoded constant
6. Write Vitest test: render the settings panel with a mock `GlobalConfig`; confirm the Server section displays `db_path` and `active_agent_types`

## Verification

### Auto-Verify

- [ ] `npx tsc --noEmit` passes with no type errors
- [ ] `getConfig` is exported from `ui/src/api/client.ts`
- [ ] `useGlobalConfig` is exported from `ui/src/hooks/useApi.ts`
- [ ] `GlobalConfig` type is defined and exported
- [ ] Vitest test for settings panel Server section passes

### Manual Verify

- [ ] Settings panel shows a "Server" section with DB path, active agent types, and max_recent_runs
- [ ] Run list respects `max_recent_runs` from the server config (not a hardcoded value)
- [ ] Server section shows an error state with retry when the config endpoint fails

## Context & References

- Bug report: `docs/bugs/UI-GLOBAL-CONFIG.md`
- Architecture: `docs/bug-removal/architecture.md` — "Modified Components: settings panel", `staleTime: Infinity` or 5 minutes for `useGlobalConfig`
- Backend endpoint: `GET /api/config` in `src/orchestrator/api/routers/`
- Performance note: long `staleTime` is intentional — config rarely changes; avoid redundant fetches on every settings mount
