# Feature: Surface Server Configuration in the UI

## Summary

The backend exposes `GET /api/config` which returns the server-side `GlobalConfig` (paths,
feature flags, dashboard limits, WebSocket settings). The frontend has no awareness of this
config; all settings are local browser state only.

## Current State

**Backend — complete:**
- `GET /api/config` — returns a JSON representation of `GlobalConfig`
  (`src/orchestrator/api/routers/config.py`)
- No dedicated integration tests yet

**Frontend — missing:**
- No `getConfig()` in `ui/src/api/client.ts`
- No `GlobalConfig` type
- No `useGlobalConfig()` hook
- Settings panel shows only local preferences with no server-derived values

## Work Required

1. **`ui/src/api/client.ts`** — add:
   ```ts
   getConfig(): Promise<GlobalConfig>
   ```

2. **`ui/src/types/`** — add `GlobalConfig` type matching the backend schema (at minimum:
   `dashboard.max_recent_runs`, `websocket.batching_enabled`, `paths.*`).

3. **`ui/src/hooks/useApi.ts`** — add `useGlobalConfig()` query with a long `staleTime`
   (config rarely changes).

4. **UI integration (minimal viable):**
   - Display read-only server config values in the settings panel under a "Server" section
     (e.g., DB path, active agent types, dashboard limits).
   - Use `max_recent_runs` from server config as the default run list page size instead of
     a hardcoded constant.

## Severity

**Low** — no functional breakage; purely an observability and consistency improvement.

## Related

- `docs/ui-gaps2/README.md §9`
- `src/orchestrator/api/routers/config.py` — endpoint
- `src/orchestrator/config/global_config.py` — `GlobalConfig` model
- `ui/src/hooks/useSettings.ts` — local settings context (complement, not replacement)
