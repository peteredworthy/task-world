# Step 11: Surface Server GlobalConfig in Settings Panel (UI-GLOBAL-CONFIG)

This step displays the server's runtime configuration (database path, active agent types, dashboard
limits) in the UI settings panel. The backend `GET /api/config` endpoint exists but the frontend
has no client function, type, hook, or UI for it. The run list currently uses a hardcoded constant
for `max_recent_runs`; after this step it will use the server-provided value. The `GlobalConfig`
query uses a long `staleTime` since configuration rarely changes.

## Intent Verification
**Original Intent**: `docs/bug-removal/intent.md` — "`useGlobalConfig` exists; settings panel shows server-derived config; run list pagination uses server `max_recent_runs`"
**Functionality to Produce**:
- `GlobalConfig` type in `ui/src/types/`
- `getConfig()` in `ui/src/api/client.ts`
- `useGlobalConfig()` query hook with long `staleTime` in `ui/src/hooks/useApi.ts`
- Settings panel "Server" section showing DB path, active agent types, `max_recent_runs`
- Run list uses `useGlobalConfig().data.max_recent_runs` instead of a hardcoded constant

**Final Verification Criteria**:
- `npx tsc --noEmit` passes with no type errors
- `getConfig` exported from `client.ts`
- `useGlobalConfig` exported from `useApi.ts`
- `GlobalConfig` type exported from `ui/src/types/`
- Vitest test for settings panel Server section passes

---

## Task 1: Add GlobalConfig type and getConfig client function
**Description**:
Add the `GlobalConfig` TypeScript type and `getConfig()` client function.

**Implementation Plan (Do These Steps)**
- [ ] Add `GlobalConfig` to `ui/src/types/` (create `types/config.ts` or extend existing):
```typescript
export interface GlobalConfig {
  db_path: string;
  active_agent_types: string[];
  max_recent_runs: number;
  // add any other fields present in the backend response
}
```
- [ ] Open `ui/src/api/client.ts` and add:
```typescript
export async function getConfig(): Promise<GlobalConfig> {
  const response = await fetch('/api/config');
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}
```

**References**
- `docs/bug-removal/step-11-plan.md` — Task 1 and Task 2 descriptions
- `docs/bugs/UI-GLOBAL-CONFIG.md`
- Backend endpoint: `GET /api/config` in `src/orchestrator/api/routers/`

**Constraints**
- [ ] Only `ui/src/types/` (new file) and `ui/src/api/client.ts` should be changed in this task

**Functionality (Expected Outcomes)**
- [ ] `GlobalConfig` type exported from `ui/src/types/`
- [ ] `getConfig` exported from `ui/src/api/client.ts`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0

---

## Task 2: Add useGlobalConfig hook
**Description**:
Add the `useGlobalConfig` query hook with a long `staleTime` to avoid redundant fetches on every
mount (configuration rarely changes).

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/hooks/useApi.ts`
- [ ] Add the hook:
```typescript
export function useGlobalConfig() {
  return useQuery({
    queryKey: ['globalConfig'],
    queryFn: getConfig,
    staleTime: Infinity, // config rarely changes; no need to refetch on every mount
    // alternatively: staleTime: 5 * 60 * 1000, // 5 minutes
  });
}
```

**References**
- `docs/bug-removal/step-11-plan.md` — Task 3 description
- `docs/bug-removal/architecture.md` — "Technology Choices: GlobalConfig staleTime: Infinity or 5 minutes"

**Constraints**
- [ ] Only `ui/src/hooks/useApi.ts` should be changed in this task
- [ ] `staleTime` must be set to `Infinity` or at least 5 minutes (300_000 ms)

**Functionality (Expected Outcomes)**
- [ ] `useGlobalConfig` exported from `ui/src/hooks/useApi.ts`
- [ ] Query uses a long `staleTime` (Infinity or 5 minutes)

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `grep -n "useGlobalConfig" ui/src/hooks/useApi.ts` shows the export

---

## Task 3: Update settings panel and run list, write Vitest test
**Description**:
Update the settings panel component to include a "Server" section using `useGlobalConfig`, update
the run list to use `max_recent_runs` from the server config, and write a Vitest test.

**Implementation Plan (Do These Steps)**
- [ ] Locate the settings panel component (likely under `ui/src/components/` or `ui/src/pages/`)
- [ ] Add a "Server" section to the settings panel using `useGlobalConfig`:
```typescript
const { data: config, isError } = useGlobalConfig();

// In the settings panel render:
<section>
  <h2>Server</h2>
  {isError ? (
    <div>
      Unable to load server configuration.
      <button onClick={() => refetch()}>Retry</button>
    </div>
  ) : config ? (
    <dl>
      <dt>Database path</dt>
      <dd>{config.db_path}</dd>
      <dt>Active agent types</dt>
      <dd>{config.active_agent_types.join(', ')}</dd>
      <dt>Max recent runs</dt>
      <dd>{config.max_recent_runs}</dd>
    </dl>
  ) : (
    <div>Loading...</div>
  )}
</section>
```
- [ ] Locate the run list component and replace any hardcoded `max_recent_runs` constant with `useGlobalConfig().data?.max_recent_runs ?? <default_fallback>`
- [ ] Write a Vitest test for the settings panel "Server" section:
```typescript
const mockConfig: GlobalConfig = {
  db_path: '/data/orchestrator.db',
  active_agent_types: ['claude', 'openhands'],
  max_recent_runs: 20,
};

test('settings panel renders server section with db_path and agent types', () => {
  // mock useGlobalConfig to return mockConfig
  render(<SettingsPanel />);
  expect(screen.getByText('/data/orchestrator.db')).toBeInTheDocument();
  expect(screen.getByText(/claude/i)).toBeInTheDocument();
});
```
- [ ] Run `npx vitest run` and confirm all tests pass

**References**
- `docs/bug-removal/step-11-plan.md` — Task 4, Task 5, Task 6 descriptions
- `docs/bug-removal/architecture.md` — "Modified Components: settings panel"

**Constraints**
- [ ] Only the settings panel component and the run list component should be changed (plus the new test file)

**Functionality (Expected Outcomes)**
- [ ] Settings panel shows a "Server" section with DB path, active agent types, and max_recent_runs
- [ ] Run list uses `max_recent_runs` from `useGlobalConfig` (not a hardcoded constant)
- [ ] Settings panel shows error state with retry when `getConfig` fails
- [ ] Vitest test for settings panel Server section passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `npx vitest run` exits 0 (all tests pass including the new settings panel test)
